from flask import Flask, render_template, request, redirect, url_for
import docker
import sqlite3
import os

app = Flask(__name__)
client = docker.from_env()

def initialize_db():
    connection = sqlite3.connect('container_db.sqlite')
    cursor = connection.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS ports (portcount INTEGER)''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS container_notes (
            container_id TEXT PRIMARY KEY,
            notes TEXT
        )
    ''')
    cursor.execute('''INSERT OR IGNORE INTO ports (portcount) VALUES (5900)''')
    connection.commit()
    connection.close()




initialize_db()

def get_container_notes(container_id):
    connection = sqlite3.connect('container_db.sqlite')
    cursor = connection.cursor()
    cursor.execute('SELECT notes FROM container_notes WHERE container_id = ?', (container_id,))
    notes = cursor.fetchone()
    connection.close()
    return notes[0] if notes else ''

def archived_containers():
    base_path = '/home/user/archived'
    archived_files = []
    
    if os.path.exists(base_path):
        archived_files = os.listdir(base_path)
    
    return archived_files


def get_next_port():
    connection = sqlite3.connect('container_db.sqlite')
    cursor = connection.cursor()
    cursor.execute('''UPDATE ports SET portcount = portcount + 1''')
    connection.commit()
    cursor.execute('''SELECT portcount FROM ports''')
    portcount = cursor.fetchone()[0]
    connection.close()
    return portcount

def get_containers():
    running_containers = client.containers.list()
    stopped_containers = client.containers.list(all=True, filters={"status": "exited"})

    #archived ones
    base_path = '/home/user/archived'
    archived_files = []
    
    if os.path.exists(base_path):
        archived_files = os.listdir(base_path)
    
    container_stats = {}  # Dictionary to hold container statistics
    
    for container in running_containers:
        stats = container.stats(stream=False)  # Get container stats
        container_stats[container.id] = stats  # Store stats in the dictionary
    
    return running_containers, stopped_containers, container_stats, archived_files


@app.route('/')
def index():
    running_containers, stopped_containers, container_stats, archived_files = get_containers()
    return render_template(
        'containers.html', 
        running_containers=running_containers, 
        stopped_containers=stopped_containers, 
        container_stats=container_stats,
        get_container_notes=get_container_notes,
        archived_files=archived_files
    )


@app.route('/create_container', methods=['POST'])
def create_container():
    port = get_next_port()
    env_vars = {
        'VNC_PASSWORD': '1234',
        'VNC_RESOLUTION': '640x480x16'
    }
    container_name = request.form['container_name']
    notes = request.form['notes']
    print("DEBUG: CREATE: name, notes", container_name, notes)
    container = client.containers.run(
        'xp5ubnt:latest',
        detach=True,
        ports={'5900/tcp': port},
        environment=env_vars,
        name=container_name  # Set the container name
    )
    
    # Save notes to SQLite database
    save_notes_to_database(container_name, notes)
    
    return redirect(url_for('index'))

@app.route('/view_logs', methods=['POST'])
def view_logs():
    container_id = request.form['container_id']
    container = client.containers.get(container_id)
    logs = container.logs().decode('utf-8')
    return logs

@app.route('/start_container', methods=['POST'])
def start_container():
    container_id = request.form['container_id']
    container = client.containers.get(container_id)
    
    if container.status == 'exited':  # Check if the container is in "exited" state
        container.start()  # Start the container
        return redirect(url_for('index'))  # Redirect back to the main page
    else:
        print("error-already running")

@app.route('/stop_container', methods=['POST'])
def stop_container():
    container_id = request.form['container_id']
    container = client.containers.get(container_id)
    container.stop()
    return redirect(url_for('index'))


@app.route('/update_notes', methods=['POST'])
def update_notes():
    container_id = request.form['container_id']
    updated_notes = request.form['updated_notes']

    # Update notes in the database
    save_notes_to_database(container_id, updated_notes)

    return redirect(url_for('index'))




@app.route('/connect_vnc', methods=['POST'])
def connect_vnc():
    try:
        container_id = request.form['container_id']
        app.logger.debug(f"Received container_id: {container_id}")
        
        container = client.containers.get(container_id)
        port = container.attrs['NetworkSettings']['Ports']['5900/tcp'][0]['HostPort']
        vnc_url = f'http://192.168.1.148:{port}'
        
        app.logger.debug(f"Constructed VNC URL: {vnc_url}")
        
        return render_template('vnc_viewer.html', vnc_url=vnc_url)
    except Exception as e:
        app.logger.error(f"Error: {e}")
        return "Error occurred", 500

def save_notes_to_database(container_id, notes):
    connection = sqlite3.connect('container_db.sqlite')
    cursor = connection.cursor()
    #new container notes dont save because we have yet to learn waht the container ID is
    # need to 2 step it or save together in one go
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO container_notes (container_id, notes) 
            VALUES (?, ?)
        ''', (container_id, notes))
        connection.commit()
    except sqlite3.Error as e:
        print("Error:", e)
        # Handle the error, e.g., return an error message to the user
        
    connection.close()


@app.route('/archive_container', methods=['POST'])
def archive_container():
    container_id = request.form.get('container_id')
    container = client.containers.get(container_id)

    image_name = f"archived_{container_id}"
    container.commit(repository=image_name, tag='latest')

    image_template_tar = os.path.join('/home/user/archived', f"{image_name}.tar")
    container_image = client.images.get(image_name)
    with open(image_template_tar, 'wb') as f:
        for chunk in container_image.save():
            f.write(chunk)

    return redirect(url_for('index'))

@app.route('/create_from_archive', methods=['POST'])
def create_from_archive():
    archived_file = request.form.get('archived_file')

    base_path = '/home/user/archived'
    archived_file_path = os.path.join(base_path, archived_file)

    # Load the archived image into Docker as an image
    with open(archived_file_path, 'rb') as f:
        docker_image = client.images.load(f.read())[0]

    # Run a container from the loaded image
    container = client.containers.run(docker_image.id, detach=True)

    return redirect(url_for('index'))




if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
