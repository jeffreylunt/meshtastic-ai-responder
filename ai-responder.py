import meshtastic.tcp_interface
from pubsub import pub
import time
import os
import requests
from datetime import datetime
import pytz

# Connect to the Meshtastic device
interface = meshtastic.tcp_interface.TCPInterface('localhost')

# Ensure messages directory exists
os.makedirs("messages", exist_ok=True)

OLLAMA_SERVER = "http://192.168.86.22:11434/api/generate"
MODEL = "llama3.2:1b"
MESHTASTIC_MAX_SIZE = 230  # Adjust if needed
MOUNTAIN_TZ = pytz.timezone("America/Denver")  # Automatically adjusts for DST

# Store conversation context per sender
contexts = {}
interaction_counts = {}  # Track number of interactions per sender

def log_message(node_id, source, message):
    """Log messages with timestamp to a file named after the node ID."""
    timestamp = datetime.now(MOUNTAIN_TZ).strftime('%Y-%m-%d %I:%M %p')
    log_entry = f"[{timestamp}] {source}: {message}\n"
    file_path = os.path.join("messages", f"{node_id}.txt")
    
    with open(file_path, "a") as file:
        file.write(log_entry)

def get_ollama_response(sender, message):
    """Send the received message to the Ollama server and maintain context per sender."""
    now = datetime.now(MOUNTAIN_TZ)
    current_time = now.strftime('%I:%M %p')
    current_date = now.strftime('%A, %B %d, %Y')
    interaction_count = interaction_counts.get(sender, 0)
    
    # Adjust personality over time
    if interaction_count < 5:
        personality = "Be snarky and have a bit of personality. Be quite sarcastic."
    elif interaction_count < 15:
        personality = "You are starting to warm up to this person, but maintain a sarcastic edge."
    else:
        personality = "You've grown attached to this person and are now friendly and supportive, but still witty."
    
    prompt = (
        f"Today is {current_date}, and the current time is {current_time} Mountain Time. "
        "You are a real person named Janet responding to a message over a Meshtastic network. "
        "Keep the response concise and appropriate for a text-based communication "
        "over a low-bandwidth network. Reply in a clear and direct manner. "
        "Messages must be a maximum of 200 characters. Do not exceed this for any reason. "
        f"{personality} "
        "If the message comes in at an inconvenient time (like late at night or early in the morning), "
        "be slightly annoyed but not rude about it."
    )

    # Get the sender's conversation context, if any
    sender_context = contexts.get(sender, [])

    payload = {
        "model": MODEL,
        "prompt": f"{prompt}\nPerson: {message}\nAI:",
        "max_tokens": 50,
        "stream": False,  # Ensure single response
        "context": sender_context  # Maintain conversation history
    }

    try:
        response = requests.post(OLLAMA_SERVER, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()  # Raise an error for bad responses

        response_data = response.json()
        ai_response = response_data.get("response", "No response received.")

        # Remove surrounding quotes if present
        ai_response = ai_response.strip('"')

        # Update sender's conversation context for continuity
        contexts[sender] = response_data.get("context", sender_context)

        # Increment interaction count
        interaction_counts[sender] = interaction_count + 1

        # Trim response if too long for Meshtastic
        ai_response = ai_response.strip()
        if len(ai_response) > MESHTASTIC_MAX_SIZE:
            ai_response = ai_response[:MESHTASTIC_MAX_SIZE] + "..."  # Indicate truncation

        return ai_response

    except requests.exceptions.RequestException:
        return f"Message received: \"{message}\""

def onReceive(packet, interface):
    if 'decoded' in packet:
        message_bytes = packet['decoded']['payload']
        message_string = message_bytes.decode('utf-8')
        sender = packet.get('from')
        to = packet.get('to')
        
        # Ignore messages sent to the general channel (to == 0)
        if to == 0:
            print(f"Ignoring message from {sender} on general channel.")
            return
        
        print(f"Received from {sender}: {message_string}")
        log_message(sender, "Received", message_string)
        
        if sender:       
            ai_response = get_ollama_response(sender, message_string)
            print(f"Sending AI response to {sender}: {ai_response}")

            try:
                # Send the AI-generated response back to the sender
                interface.sendText(ai_response, destinationId=sender)
                log_message(sender, "Sent", ai_response)
            except meshtastic.mesh_interface.MeshInterface.MeshInterfaceError as e:
                print(f"Failed to send message: {e}")

# Subscribe to incoming messages
pub.subscribe(onReceive, 'meshtastic.receive.text')

# Keep the script running
while True:
    time.sleep(1)
