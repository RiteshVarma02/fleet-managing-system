import subprocess
import os

def get_active_topics(domain_id=12):
    try:
        # Fetch all active topics in the specified domain
        topics_output = subprocess.check_output(f"ros2 topic list --all --domain {domain_id}", shell=True, text=True)
        topics = topics_output.strip().split('\n')
        return topics
    except subprocess.CalledProcessError as e:
        print(f"Error fetching topics: {e}")
        return []

def print_topic_info(domain_id):
    print("Fetching active topics and printing their info...")
    topics = get_active_topics(domain_id)
    if not topics:
        print("No active topics found.")
        return

    for topic in topics:
        try:
            print(f"\n--- Topic: {topic} ---")
            # Get the type of the message for the topic
            topic_type_output = subprocess.check_output(f"ros2 topic info {topic} --domain {domain_id}", shell=True, text=True)
            topic_type = [line.split('type: ')[1].strip() for line in topic_type_output.split('\n') if 'type:' in line][0]
            print(f"Topic Type: {topic_type}")

            # Echo the messages on the topic
            echo_output = subprocess.check_output(f"ros2 topic echo {topic} --domain {domain_id} -n 1", shell=True, text=True)
            print("Message Data:")
            print(echo_output)
        except subprocess.CalledProcessError as e:
            print(f"Error processing topic {topic}: {e}")
            continue

if __name__ == "__main__":
    domain_id = 12
    print_topic_info(domain_id)