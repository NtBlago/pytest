import requests
import time
import os
from datetime import datetime

API_BASE = "https://mephi.opentoshi.net/api/v1"
TEAM_NAME = "Reverse_oreo_team"

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reactor_log.txt")


def write_log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Log write error: {e}")


class ReactorAPI:
    def __init__(self):
        self.team_id = None
        write_log("Program started")
        self.register_team()

    def register_team(self):
        resp = requests.get(f"{API_BASE}/team/register", params={"name": TEAM_NAME})

        if resp.status_code == 200:
            response_data = resp.json()
            if "data" in response_data:
                data = response_data["data"]
                self.team_id = data.get("team_id")
            else:
                self.team_id = response_data.get("team_id") or response_data.get("id") or response_data.get("teamId")

            if self.team_id:
                write_log(f"Team registered successfully. Team ID: {self.team_id}")
                print(f"Team ID: {self.team_id}")
            else:
                write_log("ERROR: No team_id in server response")
                raise Exception("No team_id in server response")
        else:
            write_log(f"ERROR: Registration failed. Code: {resp.status_code}")
            raise Exception(f"Registration failed. Code: {resp.status_code}")

    def create_reactor(self):
        resp = requests.post(f"{API_BASE}/reactor/create_reactor", params={"team_id": self.team_id})
        if resp.status_code == 200:
            write_log("Reactor created successfully")
        else:
            write_log(f"ERROR: Failed to create reactor. Code: {resp.status_code}")
        return resp.status_code == 200

    def reset_reactor(self):
        resp = requests.post(f"{API_BASE}/reactor/reset_reactor", params={"team_id": self.team_id})
        if resp.status_code == 200:
            write_log("Reactor reset successfully")
        else:
            write_log(f"ERROR: Failed to reset reactor. Code: {resp.status_code}")
        return resp.status_code == 200

    def set_speed(self, speed):
        resp = requests.post(f"{API_BASE}/reactor/set-speed",
                             params={"team_id": self.team_id, "speed": speed})
        if resp.status_code == 200:
            write_log(f"Simulation speed set to {speed}x")
        else:
            write_log(f"ERROR: Failed to set speed to {speed}x. Code: {resp.status_code}")
        return resp.status_code == 200

    def refill_water(self, amount):
        resp = requests.post(f"{API_BASE}/reactor/refill-water",
                             params={"team_id": self.team_id, "amount": amount})
        if resp.status_code == 200:
            write_log(f"Water refilled: +{amount}L")
        else:
            write_log(f"ERROR: Failed to refill water ({amount}L). Code: {resp.status_code}")
        return resp.status_code == 200

    def activate_cooling(self, seconds):
        resp = requests.post(f"{API_BASE}/reactor/activate-cooling",
                             params={"team_id": self.team_id, "amount": seconds})
        if resp.status_code == 200:
            write_log(f"Cooling activated: {seconds} seconds")
        else:
            write_log(f"ERROR: Failed to activate cooling ({seconds}s). Code: {resp.status_code}")
        return resp.status_code == 200

    def emergency_shutdown(self):
        resp = requests.post(f"{API_BASE}/reactor/emergency-shutdown",
                             params={"team_id": self.team_id})
        if resp.status_code == 200:
            write_log("EMERGENCY SHUTDOWN activated")
        else:
            write_log(f"ERROR: Failed to activate emergency shutdown. Code: {resp.status_code}")
        return resp.status_code == 200

    def get_data(self):
        try:
            resp = requests.get(f"{API_BASE}/reactor/data", params={"team_id": self.team_id}, timeout=5)
            if resp.status_code == 200:
                response_data = resp.json()
                if "data" in response_data and "reactor_state" in response_data["data"]:
                    return response_data["data"]["reactor_state"]
                elif "data" in response_data:
                    return response_data["data"]
                return response_data
            else:
                write_log(f"ERROR: Failed to get data. Code: {resp.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            write_log(f"ERROR: Request exception in get_data: {e}")
            return None


def auto_protection(api, temp, rad, water):
    actions_taken = False

    if water < 40:
        write_log(f"AUTO: Water level {water:.2f}% below 40% - initiating refill")
        print(f"WARNING: Water level {water:.2f}% below 40% - refilling water")
        api.refill_water(30)
        actions_taken = True

    if temp >= 1200:
        write_log(f"AUTO: Temperature {temp:.2f}C exceeds 1200C - initiating cooling")
        print(f"WARNING: Temperature {temp:.2f}C exceeds 1200C - activating cooling")
        api.activate_cooling(10)
        actions_taken = True

    if rad >= 150:
        write_log(f"AUTO: Radiation {rad:.2f} exceeds 150 - initiating cooling")
        print(f"WARNING: Radiation {rad:.2f} exceeds 150 - activating cooling")
        api.activate_cooling(10)
        actions_taken = True

    if temp >= 1250 or rad >= 200:
        write_log(f"AUTO: CRITICAL - Temp={temp:.2f}C, Rad={rad:.2f} - emergency shutdown")
        print("CRITICAL: Emergency shutdown required!")
        api.emergency_shutdown()
        actions_taken = True

    return actions_taken


print("Starting reactor...")
write_log("=== SESSION START ===")

try:
    api = ReactorAPI()
    api.create_reactor()

    while True:
        try:
            sim_speed = float(input("Enter simulation speed (1-10): "))
            if 1 <= sim_speed <= 10:
                api.set_speed(sim_speed)
                write_log(f"User set simulation speed to {sim_speed}x")
                break
            else:
                print("Please enter a number between 1 and 10")
        except ValueError:
            print("Please enter a valid number")

    while True:
        try:
            monitor_interval = float(input("Enter monitoring interval in seconds (1-10): "))
            if 1 <= monitor_interval <= 10:
                write_log(f"Monitoring started with interval={monitor_interval}s")
                print(f"Monitoring started with {monitor_interval}s interval and auto-protection...")
                break
            else:
                print("Please enter a number between 1 and 10")
        except ValueError:
            print("Please enter a valid number")

    while True:
        data = api.get_data()
        if data:
            temp = data.get('temperature', 0)
            water = data.get('water_level', 0)
            rad = data.get('radiation', 0)
            speed = data.get('simulation_speed', 1)
            emergency = data.get('emergency_active', False)
            exploded = data.get('exploded', False)
            exploded_at = data.get('exploded_at', None)

            print(f"\nTemp: {temp:.2f}C | Water: {water:.2f}% | Rad: {rad:.2f}")
            print(f"Simulation speed: {speed}x | Emergency: {emergency}")

            if not emergency and not exploded:
                actions = auto_protection(api, temp, rad, water)
                if actions:
                    write_log(f"Auto-protection triggered at Temp={temp:.2f}, Water={water:.2f}, Rad={rad:.2f}")

            if exploded:
                write_log(f"REACTOR EXPLODED at {exploded_at if exploded_at else 'unknown time'}")
                print(f"EXPLODED at {exploded_at if exploded_at else 'unknown time'}")
                break

            if emergency:
                print("EMERGENCY MODE ACTIVE - Reactor is shutting down")
        else:
            write_log("WARNING: No data from server")
            print("No data from server")

        time.sleep(monitor_interval)

except KeyboardInterrupt:
    write_log("Program stopped by user (KeyboardInterrupt)")
    print("\nMonitoring stopped")
except Exception as e:
    write_log(f"FATAL ERROR: {e}")
    print(f"Error: {e}")
finally:
    write_log("=== SESSION END ===")
    print(f"\nLog file saved to: {LOG_FILE}")