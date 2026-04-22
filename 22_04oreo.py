import requests

API_BASE = "http://mephi.opentoshi.net/api/v1"
TEAM_NAME = "Reverse_oreo"


class ReactorAPI:

    def init(self):
        self.team_id = None
        self.connected = False
        self.register_team()

    def register_team(self):
        try:
            print(f"[API] Регистрация команды '{TEAM_NAME}'...")
            response = requests.get(f"{API_BASE}/team/register",
                                    params={"name": TEAM_NAME},
                                    timeout=5)

            if response.status_code == 200:
                data = response.json()
                self.team_id = data.get("team_id")
                self.connected = True
                print(f"[API] Регистрация успешна! Team ID: {self.team_id}")
                return True
            else:
                print(f"[API] Ошибка регистрации: {response.status_code}")
                self.connected = False
                return False

        except requests.exceptions.ConnectionError:
            print("[API] Нет соединения с сервером!")
            self.connected = False
            return False
        except Exception as e:
            print(f"[API] Ошибка: {e}")
            self.connected = False
            return False

    def create_reactor(self):
        if not self.connected:
            return False
        try:
            response = requests.post(f"{API_BASE}/reactor/create_reactor",
                                     params={"team_id": self.team_id},
                                     timeout=5)
            if response.status_code == 200:
                print("[API] Реактор создан")
                return True
        except:
            pass
        return False

    def reset_reactor(self):
        if not self.connected:
            return False
        try:
            response = requests.post(f"{API_BASE}/reactor/reset_reactor",
                                     params={"team_id": self.team_id},
                                     timeout=5)
            if response.status_code == 200:
                print("[API] Реактор сброшен")
                return True
        except:
            pass
        return False

    def set_speed(self, speed):
        if not self.connected:
            return False
        try:
            response = requests.post(f"{API_BASE}/reactor/set-speed",
                                     params={"team_id": self.team_id, "speed": speed},
                                     timeout=5)
            return response.status_code == 200
        except:
            return False

    def refill_water(self, amount):
        if not self.connected:
            return False
        try:
            response = requests.post(f"{API_BASE}/reactor/refill-water",
                                     params={"team_id": self.team_id, "amount": amount},
                                     timeout=5)
            return response.status_code == 200
        except:
            return False

    def activate_cooling(self, seconds):
        if not self.connected:
            return False
        try:
            response = requests.post(f"{API_BASE}/reactor/activate-cooling",
                                     params={"team_id": self.team_id, "amount": seconds},
                                     timeout=5)
            return response.status_code == 200
        except:
            return False

    def emergency_shutdown(self):
        if not self.connected:
            return False
        try:
            response = requests.post(f"{API_BASE}/reactor/emergency-shutdown",
                                     params={"team_id": self.team_id},
                                     timeout=5)
            return response.status_code == 200
        except:
            return False

    def get_data(self):
        if not self.connected:
            return None
        try:
            response = requests.get(f"{API_BASE}/reactor/data",
                                    params={"team_id": self.team_id},
                                    timeout=3)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return None