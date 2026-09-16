from zk import ZK, const
import pandas as pd
from dateutil import parser
from datetime import datetime, time
import socket


def check_network_reachable(ip_address, port, timeout=3):
    """Raw TCP-connect test, independent of the ZK protocol itself. Lets the
    caller tell "device unreachable on the network" apart from "reachable,
    but the ZK handshake failed" (wrong comm key, non-ZK service on that
    port, etc.) instead of one generic connection error."""
    try:
        with socket.create_connection((ip_address, port), timeout=timeout):
            return True, "OK"
    except socket.timeout:
        return False, "Tiempo de espera agotado (sin respuesta) — revisa la IP, la red o si el equipo está encendido."
    except (ConnectionRefusedError, OSError) as e:
        return False, f"No se pudo abrir conexión al puerto {port}: {e}"


class ZKTecoAttendance:
    def __init__(self, ip_address, port=4370, timeout=5, password=0):
        self.ip_address = ip_address
        self.port = port
        self.timeout = timeout
        self.password = password
        self.zk = ZK(self.ip_address, port=self.port, timeout=self.timeout, password=self.password)
        self.conn = None
        self.users = {}  # Cache for user information
        self.device_info = {}  # Cache for device model/serial/firmware

    def connect(self):
        try:
            self.conn = self.zk.connect()
            # Load user information
            self.load_users()
            self.load_device_info()
            print(f"Successfully connected to device at {self.ip_address}")
        except Exception as e:
            print(f"Error connecting to device: {str(e)}")
            self.conn = None

    def disconnect(self):
        if self.conn:
            try:
                self.conn.disconnect()
                print("Disconnected from device")
            except Exception as e:
                # A device that just had a corrupted/large transfer can also
                # fail the disconnect handshake itself (e.g. "TCP packet
                # invalid") -- that failure doesn't mean anything is still
                # open on our end, so don't let it crash whatever the caller
                # was doing (it's usually cleanup in a finally block).
                print(f"Warning: error while disconnecting ({e}) -- dropping the connection anyway")
            finally:
                self.conn = None
                self.users = {}
                self.device_info = {}

    def restart_device(self):
        """Reboot the terminal remotely. Ends the current connection (the
        device drops it as it restarts) -- reconnect after a few seconds."""
        if not self.conn:
            raise RuntimeError("Not connected to device. Please connect first.")
        self.conn.restart()
        self.conn = None
        self.users = {}
        self.device_info = {}

    def poweroff_device(self):
        """Power the terminal off remotely. It will need to be turned back
        on manually -- unlike restart, it will not come back by itself."""
        if not self.conn:
            raise RuntimeError("Not connected to device. Please connect first.")
        self.conn.poweroff()
        self.conn = None
        self.users = {}
        self.device_info = {}

    def clear_attendance_log(self):
        """Wipe every punch stored ON THE DEVICE ITSELF. Irreversible on
        the device side -- there is no undo. Does NOT touch enrolled users
        (fingerprints/cards stay) and has no effect at all on whatever is
        already saved in the central database, which is the whole point:
        this only resets what the terminal has to re-send next time, so it
        starts accumulating from zero without losing the history already
        synced centrally."""
        if not self.conn:
            raise RuntimeError("Not connected to device. Please connect first.")
        self.conn.clear_attendance()

    def load_device_info(self):
        """Read model/serial/firmware info reported by the device itself."""
        if not self.conn:
            return
        info = {}
        for key, getter in (
            ('model', self.conn.get_device_name),
            ('platform', self.conn.get_platform),
            ('serial_number', self.conn.get_serialnumber),
            ('firmware_version', self.conn.get_firmware_version),
        ):
            try:
                info[key] = getter()
            except Exception as e:
                print(f"Could not read device {key}: {str(e)}")
                info[key] = ""
        self.device_info = info
        return info

    def load_users(self):
        """Load all users from the device"""
        if not self.conn:
            return
        try:
            users = self.conn.get_users()
            self.users = {user.user_id: user.name for user in users}
            print(f"Loaded {len(self.users)} users from device")
        except Exception as e:
            print(f"Error loading users: {str(e)}")

    def list_device_users(self):
        """Users currently enrolled on the physical device (not the attendance log)."""
        if not self.conn:
            return []
        users = self.conn.get_users()
        return [{
            'uid': u.uid,
            'user_id': u.user_id,
            'name': u.name,
            'privilege': u.privilege,
            'card': u.card,
        } for u in users]

    def create_or_update_user(self, user_id, name, privilege=0, password='', card=0):
        """Create a new employee on the device, or update them if user_id already
        exists there. Matching by user_id (not uid) is what keeps this from ever
        creating a duplicate person under a second internal slot."""
        if not self.conn:
            raise RuntimeError("Not connected to device. Please connect first.")
        user_id = str(user_id)
        existing = next((u for u in self.conn.get_users() if u.user_id == user_id), None)
        uid = existing.uid if existing else None
        self.conn.set_user(
            uid=uid, name=name, privilege=privilege,
            password=password, user_id=user_id, card=card,
        )
        self.load_users()
        return uid is None  # True if this created a new user, False if it updated one

    def delete_device_user(self, user_id):
        """Remove an employee (and their fingerprints) from the device."""
        if not self.conn:
            raise RuntimeError("Not connected to device. Please connect first.")
        user_id = str(user_id)
        existing = next((u for u in self.conn.get_users() if u.user_id == user_id), None)
        if not existing:
            raise ValueError(f"No user with user_id={user_id} exists on this device")
        self.conn.delete_user(uid=existing.uid, user_id=user_id)
        self.load_users()

    def get_attendance_status(self, punch):
        """Convert punch value to check-in/check-out status"""
        # According to ZKTeco documentation:
        # 0: Check In
        # 1: Check Out
        punch_map = {
            0: "Check In",
            1: "Check Out"
        }
        return punch_map.get(punch, f"Unknown Punch ({punch})")

    def get_raw_attendance(self, start_date=None, end_date=None, device_name=None):
        """Return each individual punch (no check-in/check-out grouping).
        Raises on a real transfer/protocol error (e.g. "TCP packet invalid")
        instead of swallowing it -- the caller needs to tell that apart from
        "the device genuinely has zero records" to retry or report it."""
        if not self.conn:
            print("Not connected to device. Please connect first.")
            return None
        attendance = self.conn.get_attendance()
        if not attendance:
            print("No attendance records found")
            return None

        if start_date and not isinstance(start_date, datetime):
            start_date = datetime.combine(start_date, time.min)
        if end_date and not isinstance(end_date, datetime):
            end_date = datetime.combine(end_date, time.max)

        raw_records = []
        for att in attendance:
            dt = att.timestamp
            if start_date and end_date:
                if not (start_date <= dt <= end_date):
                    continue
            user_name = self.users.get(att.user_id, "Unknown")
            raw_records.append({
                'user_id': att.user_id,
                'user_name': user_name,
                'timestamp': dt,
                'status': self.get_attendance_status(att.punch),
                'device_name': device_name or 'Unknown'
            })

        df = pd.DataFrame(raw_records)
        if df.empty:
            return None
        df = df.sort_values(['timestamp'])
        return df

    def get_attendance(self, start_date=None, end_date=None):
        """Raises on a real transfer/protocol error instead of swallowing
        it -- see get_raw_attendance for why."""
        if not self.conn:
            print("Not connected to device. Please connect first.")
            return None
        attendance = self.conn.get_attendance()
        if not attendance:
            print("No attendance records found")
            return None

        print(f"Retrieved {len(attendance)} attendance records")

        # Convert dates to datetime objects if they're not already
        if start_date and not isinstance(start_date, datetime):
            start_date = datetime.combine(start_date, time.min)
        if end_date and not isinstance(end_date, datetime):
            end_date = datetime.combine(end_date, time.max)

        # First, collect all records
        raw_records = []
        for att in attendance:
            dt = att.timestamp
            if start_date and end_date:
                if not (start_date <= dt <= end_date):
                    continue
            user_name = self.users.get(att.user_id, "Unknown")
            raw_records.append({
                'user_id': att.user_id,
                'user_name': user_name,
                'timestamp': dt,
                'raw_status': att.status,
                'punch': att.punch,
                'status': self.get_attendance_status(att.punch)
            })

        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(raw_records)
        if df.empty:
            return None

        # Sort by user_id and timestamp
        df = df.sort_values(['user_id', 'timestamp'])

        # Group records by user and date
        grouped_records = []
        current_user = None
        current_date = None
        check_in = None
        check_out = None

        for _, row in df.iterrows():
            user_id = row['user_id']
            user_name = row['user_name']
            timestamp = row['timestamp']
            date = timestamp.date()
            punch = row['punch']

            # If new user or new date, save previous record and start new one
            if current_user != user_id or current_date != date:
                if current_user is not None and (check_in is not None or check_out is not None):
                    grouped_records.append({
                        'user_id': current_user,
                        'user_name': current_user_name,
                        'date': current_date,
                        'check_in': check_in,
                        'check_out': check_out
                    })
                current_user = user_id
                current_user_name = user_name
                current_date = date
                check_in = None
                check_out = None

            # Update check-in or check-out time
            if punch == 0:  # Check In
                check_in = timestamp
            elif punch == 1:  # Check Out
                check_out = timestamp

        # Add the last record
        if current_user is not None and (check_in is not None or check_out is not None):
            grouped_records.append({
                'user_id': current_user,
                'user_name': current_user_name,
                'date': current_date,
                'check_in': check_in,
                'check_out': check_out
            })

        # Convert to DataFrame
        result_df = pd.DataFrame(grouped_records)

        # Calculate duration if both check-in and check-out are present
        if not result_df.empty:
            result_df['duration'] = result_df.apply(
                lambda row: (row['check_out'] - row['check_in']).total_seconds() / 3600
                if pd.notnull(row['check_out']) and pd.notnull(row['check_in']) else None,
                axis=1
            )

        print(f"\nGrouped into {len(result_df)} attendance records")
        if not result_df.empty:
            print("\nSample of grouped records:")
            print(result_df.head())
        return result_df


def main():
    device_ip = "192.168.1.201"  # Replace with your device's IP address
    attendance_system = ZKTecoAttendance(device_ip)
    try:
        attendance_system.connect()
        if attendance_system.conn:
            attendance_records = attendance_system.get_attendance()
            if attendance_records is not None:
                print("\nAttendance Records:")
                print(attendance_records)
                attendance_records.to_csv('attendance_records.csv', index=False)
                print("\nRecords saved to 'attendance_records.csv'")
    finally:
        attendance_system.disconnect()

if __name__ == "__main__":
    main() 