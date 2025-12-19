import os
import smtplib
import ssl
from dotenv import load_dotenv

# Load the same .env file your app uses
load_dotenv()

# --- Configuration ---
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_APP_PASSWORD = os.environ.get("SENDER_APP_PASSWORD")
SMTP_SERVER = "smtp.gmail.com"
PORT = 587

# --- Main Test Logic ---
print("--- Starting SMTP Connection Test ---")

if not SENDER_EMAIL or not SENDER_APP_PASSWORD:
    print("Error: SENDER_EMAIL or SENDER_APP_PASSWORD not found in .env file.")
    exit()

print(f"Attempting to connect to {SMTP_SERVER} on port {PORT}...")

context = ssl.create_default_context()
server = None

try:
    # We set a short timeout of 15 seconds to get a quick response
    server = smtplib.SMTP(SMTP_SERVER, PORT, timeout=15)
    print("Connection successful. Securing connection with STARTTLS...")
    
    server.starttls(context=context)
    print("Connection secured. Attempting to log in...")
    
    server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
    print("\nSUCCESS: Login successful! Your credentials and network connection are working correctly.")

except smtplib.SMTPAuthenticationError:
    print("\nERROR: Authentication failed. The username or password is incorrect.")
except ConnectionRefusedError:
    print("\nERROR: Connection was refused by the server. This is unusual for Gmail.")
except smtplib.SMTPConnectError:
    print("\nERROR: A connection error occurred. This could be a local firewall issue.")
except TimeoutError:
    print("\nCRITICAL ERROR: The connection timed out. This is strong evidence that your ISP is blocking port 587.")
except Exception as e:
    print(f"\nAn unexpected error occurred: {e}")
finally:
    if server:
        server.quit()
    print("--- Test Finished ---")
