import requests
import time

API_BASE = "http://mephi.opentoshi.net/api/v1"
TEAM_NAME = "Reverse_oreo_team"


class ReactorAPI:
    def __init__(self):
        self.team_id = None
        self.register_team()

    def register_team(self):
        resp = requests.get(f"{API_BASE}/team/register", params={"name": TEAM_NAME})
        if resp.status_code == 200:
            self.team_id = resp.json()["team_id"]
            print(f"✅ Team ID: {self.team_id}")
        else:
            raise Exception("Регистрация не удалась")

    def create_reactor(self):
        requests.post(f"{API_BASE}/reactor/create_reactor", params={"team_id": self.team_id})

    def reset_reactor(self):
        requests.post(f"{API_BASE}/reactor/reset_reactor", params={"team_id": self.team_id})

    def set_speed(self, speed):
        requests.post(f"{API_BASE}/reactor/set-speed", params={"team_id": self.team_id, "speed": speed})

    def refill_water(self, amount):
        requests.post(f"{API_BASE}/reactor/refill-water", params={"team_id": self.team_id, "amount": amount})

    def activate_cooling(self, seconds):
        requests.post(f"{API_BASE}/reactor/activate-cooling", params={"team_id": self.team_id, "amount": seconds})

    def emergency_shutdown(self):
        requests.post(f"{API_BASE}/reactor/emergency-shutdown", params={"team_id": self.team_id})

    def get_data(self):
        resp = requests.get(f"{API_BASE}/reactor/data", params={"team_id": self.team_id})
        return resp.json() if resp.status_code == 200 else None
api = ReactorAPI()
api.create_reactor()
api.set_speed(2.0)

while True:
    data = api.get_data()
    if data:
        print(f" Темп. {data['temperature']}°C | Ур.Вод. {data['water_level']}% | Рад. {data['radiation']}")
        print(f" Скорость: {data.get('simulation_speed', 1)}x")
        if data.get('exploded'):
            print(f" ВЗРЫВ в {data.get('exploded_at')}")
            break
    time.sleep(1)