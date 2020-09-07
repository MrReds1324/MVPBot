import os.path
import pickle
from datetime import datetime

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_service():
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('sheets', 'v4', credentials=creds)


def create_sheet(sheet_name, spreadsheet_id):
    try:
        sheet = get_service().spreadsheets()
        batch_update_spreadsheet_request_body = {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
        sheet.batchUpdate(spreadsheetId=spreadsheet_id, body=batch_update_spreadsheet_request_body).execute()
        return True
    except:
        return False


def get_sheetid(sheet_name, spreadsheet_id):
    try:
        sheet = get_service().spreadsheets()
        result = sheet.get(spreadsheetId=spreadsheet_id).execute()
        for sheet in result.get('sheets', []):
            sheet_properties = sheet.get('properties', {})
            if sheet_properties.get('title', '') == sheet_name:
                return sheet_properties.get('sheetId', None)
    except:
        return None


def copy_paste(source_id, destination_id, spreadsheet_id):
    try:
        sheet = get_service().spreadsheets()
        batch_update_spreadsheet_request_body = {"requests": [{"copyPaste": {
            "source": {
                "sheetId": source_id,
                "startRowIndex": 0,
                "endRowIndex": 120,
                "startColumnIndex": 0,
                "endColumnIndex": 25
            },
            "destination": {
                "sheetId": destination_id,
                "startRowIndex": 0,
                "endRowIndex": 120,
                "startColumnIndex": 0,
                "endColumnIndex": 25
            },
            "pasteType": "PASTE_NORMAL",
            "pasteOrientation": "NORMAL"}}]}
        sheet.batchUpdate(spreadsheetId=spreadsheet_id, body=batch_update_spreadsheet_request_body).execute()
        return True
    except:
        return False


def get_sheet_data(get_range, spreadsheet_id):
    try:
        sheet = get_service().spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=get_range).execute()
        return result.get('values', [])
    except:
        return []
