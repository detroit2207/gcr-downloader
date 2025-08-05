import base64
import re
import os
import os.path
import subprocess
import sys
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseDownload
import io
import requests

# Define API scopes
SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.announcements.readonly',
    'https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

def install_prerequisites():
    """Install required Python packages if not present."""
    required_packages = [
        'google-auth',
        'google-auth-oauthlib',
        'google-auth-httplib2',
        'google-api-python-client'
    ]
    
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', '--version'])
        print("pip is available. Checking and installing required packages...")
        
        for package in required_packages:
            try:
                __import__(package)
            except ImportError:
                print(f"Installing {package}...")
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
                print(f"Successfully installed {package}")
        print("All prerequisites installed successfully.")
    except subprocess.CalledProcessError:
        print("Error: pip is not found. Please ensure Python is installed and try again.")
        print("To install Python, visit: https://www.python.org/downloads/")
        sys.exit(1)
    except Exception as e:
        print(f"Error during prerequisite installation: {e}")
        print("Please install Python and required packages manually using: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        print("To install Python, visit: https://www.python.org/downloads/")
        sys.exit(1)

def extract_course_id(classroom_link):
    """Extract and decode the course ID from a Google Classroom link."""
    match = re.search(r"/c/([A-Za-z0-9_-]+)", classroom_link)
    if not match:
        raise ValueError("Invalid Google Classroom link")
    encoded_id = match.group(1)
    try:
        decoded_id = base64.b64decode(encoded_id).decode("utf-8")
        return decoded_id
    except Exception as e:
        raise ValueError(f"Failed to decode course ID: {e}")

def authenticate():
    """Authenticate with Google API and return credentials."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError("credentials.json not found. Please download it from Google Cloud Console.")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def download_file(file_id, file_name, drive_service, output_dir):
    """Download a file from Google Drive by file ID, skipping if file exists."""
    try:
        print(f"Attempting to create directory: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)
        if not os.path.isdir(output_dir):
            raise OSError(f"Directory {output_dir} could not be created or is not accessible")

        file_path = os.path.join(output_dir, file_name)
        
        if os.path.exists(file_path):
            print(f"File {file_name} already exists at {file_path}, skipping download.")
            return
        
        request = drive_service.files().get_media(fileId=file_id)
        with open(file_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                print(f"Downloading {file_name}: {int(status.progress() * 100)}%")
        print(f"Downloaded: {file_path}")
    except PermissionError as pe:
        print(f"Permission denied when accessing {file_path}: {pe}")
    except OSError as oe:
        print(f"OS error when accessing {file_path}: {oe}")
    except Exception as e:
        print(f"Error downloading file {file_name}: {e}")

def get_folder_name_from_title(parent_title, file_name):
    """Determine folder name based on parent title or filename."""
    print(f"Debug - Raw Parent Title: {parent_title}, File Name: {file_name}")
    if parent_title is not None and parent_title.strip():
        folder_name = re.sub(r'[<>:"/\\|?*]', '_', parent_title.strip())
        return folder_name
    else:
        # No parent title, check filename
        if file_name and file_name.strip():  # Ensure file_name is not empty or just whitespace
            # Extract the first number before the dot (e.g., "1" from "1.3 Process and Threads")
            match = re.match(r'^(\d+)\.', file_name.strip())
            if match:
                module_number = match.group(1)
                print(f"Debug - Extracted Module Number: {module_number}")
                return f"Module {module_number}"
        print(f"Debug - Warning: Empty or invalid filename, defaulting to Other_Materials")
        return "Other_Materials"

def main():
    """Main function to download files from Google Classroom with folders based on parent titles or filenames."""
    try:
        install_prerequisites()

        creds = authenticate()
        classroom_service = build('classroom', 'v1', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)

        classroom_link = input("Enter the Google Classroom link: ")
        course_id = extract_course_id(classroom_link)
        print(f"Using Course ID: {course_id}")

        try:
            course = classroom_service.courses().get(id=course_id).execute()
            print(f"Course found: {course['name']}")
        except Exception as e:
            print(f"Error accessing course: {e}")
            return

        course_name = course['name'].replace(' ', '_').replace('/', '_')
        output_dir = os.path.join(os.getcwd(), course_name)
        os.makedirs(output_dir, exist_ok=True)

        # Fetch announcements
        announcements = classroom_service.courses().announcements().list(courseId=course_id).execute().get('announcements', [])
        for announcement in announcements:
            if 'materials' in announcement:
                # Use the first material's filename if no parent title exists
                first_material = announcement['materials'][0] if 'materials' in announcement and announcement['materials'] else None
                first_file_name = first_material['driveFile']['driveFile'].get('title', f"file_{first_material['driveFile']['driveFile']['id']}") if first_material and 'driveFile' in first_material else ''
                folder_name = get_folder_name_from_title(announcement.get('title', ''), first_file_name)
                folder_dir = os.path.join(output_dir, folder_name)
                os.makedirs(folder_dir, exist_ok=True)
                for material in announcement['materials']:
                    if 'driveFile' in material:
                        file = material['driveFile']['driveFile']
                        file_id = file['id']
                        file_name = file.get('title', f"file_{file_id}")
                        download_file(file_id, file_name, drive_service, folder_dir)

        # Fetch coursework materials
        materials = classroom_service.courses().courseWorkMaterials().list(courseId=course_id).execute().get('courseWorkMaterial', [])
        for material in materials:
            if 'materials' in material:
                # Use the first material's filename if no parent title exists
                first_material = material['materials'][0] if 'materials' in material and material['materials'] else None
                first_file_name = first_material['driveFile']['driveFile'].get('title', f"file_{first_material['driveFile']['driveFile']['id']}") if first_material and 'driveFile' in first_material else ''
                folder_name = get_folder_name_from_title(material.get('title', ''), first_file_name)
                folder_dir = os.path.join(output_dir, folder_name)
                os.makedirs(folder_dir, exist_ok=True)
                for item in material['materials']:
                    if 'driveFile' in item:
                        file = item['driveFile']['driveFile']
                        file_id = file['id']
                        file_name = file.get('title', f"file_{file_id}")
                        # Use filename-based folder only if no parent title
                        if material.get('title', '').strip():
                            folder_dir = os.path.join(output_dir, get_folder_name_from_title(material.get('title', ''), ''))
                        else:
                            folder_dir = os.path.join(output_dir, get_folder_name_from_title(None, file_name))
                        os.makedirs(folder_dir, exist_ok=True)
                        download_file(file_id, file_name, drive_service, folder_dir)

        print(f"All files downloaded to: {output_dir}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    main()