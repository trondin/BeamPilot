import os
import time
import threading
import tkinter as tk
import serial
import serial.tools.list_ports
from collections import deque
import configparser
import shutil
import sys
import re
from tkinter import filedialog, messagebox
from BeamPilotGui import BeamPilotGui

# External scripts
FIX_POWER_SCRIPT = "fix_power.py"
SCALE_GCODE_SCRIPT = "scale_gcode.py"
OPTIMIZE_GCODE_SCRIPT = "optimize_gcode.py"
ADJUST_SPEED_SCRIPT = "adj_speed.py"
ADJUST_POWER_SCRIPT = "adj_power.py"

# GRBL Commands
HOME_CMD = "$H"
UNLOCK_CMD = "$X"
LASER_ON_CMD = "M3 S{}"  # {} for power
LASER_OFF_CMD = "M5"
JOG_CMD = "G91 {}"  # {} for direction and step, e.g., "X-10"
RETURN_ZERO_CMD = "G90 X0 Y0"
STATUS_QUERY = "?"
SOFT_RESET = "\x18"  # Ctrl-X for reset/stop
PAUSE_CMD = "!"  # Feed hold
RESUME_CMD = "~"  # Cycle resume
SET_ZERO_CMD = "G92 X0 Y0"
BUFFER_CHECK_INTERVAL = 0.1  # Seconds to check for sending next line
POLL_INTERVAL = 1  # Seconds to poll position for real-time updates
MAX_POWER = 1000
MAX_GCODE_LINES = 100000  # Maximum number of G-code lines allowed
MAX_FILE_SIZE = 10 * 1024 * 1024  # Maximum file size in bytes (10 MB)
G1_IDLE_RE = re.compile(r'^\s*G1\s+F[\d\.]+.*[XY][+-]?\d+\.?\d*.*$', re.IGNORECASE)

class GRBLController(BeamPilotGui):
    def __init__(self):
        super().__init__()
        program_name = os.path.splitext(os.path.basename(__file__))[0]
        self.title(f"{program_name} - Laser G-code sender")
        self.geometry("800x600")

        self.protocol("WM_DELETE_WINDOW", self.quit_app)

        # Load config
        self.config_file = f'{program_name}.ini'
        self.app_config = configparser.ConfigParser()
        self.load_config()

        # Variables
        self.connected = False
        self.ser = None
        self.gcode_lines = []
        self.sent_lines = set()
        self.current_line = 0
        self.running = False
        self.paused = False
        self.response_queue = deque()
        self.abs_position = (0, 0)
        self.rel_position = (0, 0)
        self.scale_factor = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.min_x = self.min_y = self.max_x = self.max_y = 0
        self.max_working_speed = 0.0
        self.max_idle_speed = 0.0
        self.max_power = 0.0
        self.paths = []
        self.line_to_path = {}
        self.sent_commands = []
        self.gcode_loaded = False
        self.display_coords = tk.StringVar(value=self.app_config.get('Settings', 'display_coords', fallback='absolute'))
        self.last_sync_time = time.time()
        self.wcs_offset = (0, 0)
        self.last_g92_time = 0
        self.current_file = None
        self.temp_files = []
        self.power_fix_var = tk.StringVar(value=self.app_config.get('Settings', 'power_fix', fallback="1000"))
        self.max_x_var = tk.StringVar(value=self.app_config.get('Settings', 'max_x', fallback="100"))
        self.max_y_var = tk.StringVar(value=self.app_config.get('Settings', 'max_y', fallback="100"))
        self.opt_level_var = tk.StringVar(value=self.app_config.get('Settings', 'opt_level', fallback="2"))
        self.max_speed_var = tk.StringVar(value=self.app_config.get('Settings', 'max_speed', fallback="1000"))
        self.max_idle_speed_var = tk.StringVar(value=self.app_config.get('Settings', 'max_idle_speed', fallback="1000"))
        self.max_power_var = tk.StringVar(value=self.app_config.get('Settings', 'max_power', fallback="1000"))
        self.last_command = tk.StringVar(value=self.app_config.get('Settings', 'last_command', fallback=""))

        # Setup GUI
        self.setup_gui()  # Added to initialize GUI components before accessing ports_menu

        # Serial reader thread
        self.serial_thread = None
        self.poll_thread = None
        self.receive_buffer = ""  # Buffer for incoming data

        # Refresh ports on start
        self.refresh_ports()

    def load_config(self):
        try:
            self.app_config.read(self.config_file)
            if not self.app_config.has_section('Settings'):
                self.app_config.add_section('Settings')
            self.last_open_dir = self.app_config.get('Settings', 'last_open_dir', fallback=os.getcwd())
            self.last_save_dir = self.app_config.get('Settings', 'last_save_dir', fallback=None)
            self.last_port = self.app_config.get('Settings', 'last_port', fallback='')
            self.last_baudrate = self.app_config.get('Settings', 'last_baudrate', fallback='115200')
            self.last_step = self.app_config.get('Settings', 'last_step', fallback="1")
            self.last_multiplier = self.app_config.get('Settings', 'last_multiplier', fallback="1")
            self.power_fix_var = tk.StringVar(value=self.app_config.get('Settings', 'power_fix', fallback="1000"))
            self.max_x_var = tk.StringVar(value=self.app_config.get('Settings', 'max_x', fallback="100"))
            self.max_y_var = tk.StringVar(value=self.app_config.get('Settings', 'max_y', fallback="100"))
            self.opt_level_var = tk.StringVar(value=self.app_config.get('Settings', 'opt_level', fallback="2"))
            self.max_speed_var = tk.StringVar(value=self.app_config.get('Settings', 'max_speed', fallback="1000"))
            self.max_idle_speed_var = tk.StringVar(value=self.app_config.get('Settings', 'max_idle_speed', fallback="1000"))
            self.max_power_var = tk.StringVar(value=self.app_config.get('Settings', 'max_power', fallback="1000"))
            self.last_command = tk.StringVar(value=self.app_config.get('Settings', 'last_command', fallback=""))
        except Exception as e:
            print(f"Error loading configuration: {e}")
            self.last_open_dir = os.getcwd()
            self.last_save_dir = None
            self.last_port = ''
            self.last_baudrate = '115200'
            self.last_step = "1"
            self.last_multiplier = "1"
            self.power_fix_var = tk.StringVar(value="1000")
            self.max_x_var = tk.StringVar(value="100")
            self.max_y_var = tk.StringVar(value="100")
            self.opt_level_var = tk.StringVar(value="2")
            self.max_speed_var = tk.StringVar(value="1000")
            self.max_idle_speed_var = tk.StringVar(value="1000")
            self.max_power_var = tk.StringVar(value="1000")
            self.last_command = tk.StringVar(value="")

    def save_config(self):
        try:
            self.app_config.set('Settings', 'last_open_dir', self.last_open_dir)
            if self.last_save_dir:
                self.app_config.set('Settings', 'last_save_dir', self.last_save_dir)
            self.app_config.set('Settings', 'last_port', self.last_port)
            self.app_config.set('Settings', 'last_baudrate', self.last_baudrate)
            self.app_config.set('Settings', 'display_coords', self.display_coords.get())
            self.app_config.set('Settings', 'last_step', self.step_var.get())
            self.app_config.set('Settings', 'last_multiplier', self.multiplier_var.get())
            self.app_config.set('Settings', 'power_fix', self.power_fix_var.get())
            self.app_config.set('Settings', 'max_x', self.max_x_var.get())
            self.app_config.set('Settings', 'max_y', self.max_y_var.get())
            self.app_config.set('Settings', 'opt_level', self.opt_level_var.get())
            self.app_config.set('Settings', 'max_speed', self.max_speed_var.get())
            self.app_config.set('Settings', 'max_idle_speed', self.max_idle_speed_var.get())
            self.app_config.set('Settings', 'max_power', self.max_power_var.get())
            self.app_config.set('Settings', 'last_command', self.last_command.get())
            with open(self.config_file, 'w') as configfile:
                self.app_config.write(configfile)
        except Exception as e:
            print(f"Error saving configuration: {e}")

    def parse_params(self, line):
        params = {}
        i = 0
        line = line.upper()
        while i < len(line):
            if line[i].isalpha():
                key = line[i]
                i += 1
                value = ''
                sign = 1
                if i < len(line) and line[i] == '-':
                    sign = -1
                    i += 1
                while i < len(line) and (line[i].isdigit() or line[i] == '.'):
                    value += line[i]
                    i += 1
                if value:
                    try:
                        params[key] = float(value) * sign
                    except ValueError:
                        pass
            else:
                i += 1
        return params

    def model_to_canvas(self, mx, my):
        base_x = mx * 10 + 100
        base_y = -my * 10 + 500
        cx = base_x * self.scale_factor + self.offset_x
        cy = base_y * self.scale_factor + self.offset_y
        return cx, cy

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports() if not p.device.startswith('/dev/ttyS')]
        self.ports_menu['values'] = ports
        if ports:
            if self.last_port in ports:
                self.ports_var.set(self.last_port)
            else:
                self.ports_var.set(ports[0])

    def toggle_connect(self):
        if not self.connected:
            port = self.ports_var.get()
            baudrate = self.baudrate_var.get()
            
            if not port:
                print("Error: No port selected")
                messagebox.showerror("Error", "No port selected")
                return
                
            try:
                self.ser = serial.Serial(port, int(baudrate), timeout=0)  # Non-blocking mode
                self.connected = True
                self.connect_btn.config(text="Disconnect")
                
                self.last_port = port
                self.last_baudrate = baudrate
                self.save_config()
                
                self.serial_thread = threading.Thread(target=self.serial_reader, daemon=True)
                self.serial_thread.start()
                self.poll_thread = threading.Thread(target=self.poll_position, daemon=True)
                self.poll_thread.start()
                time.sleep(2)
                self.send_cmd(STATUS_QUERY, log=False)
            except Exception as e:
                print(f"Error connecting to serial port: {e}")
                messagebox.showerror("Error", f"Failed to connect: {e}")
        else:
            self.connected = False
            if self.serial_thread:
                self.serial_thread.join(timeout=1.0)
            if self.poll_thread:
                self.poll_thread.join(timeout=1.0)
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception as e:
                    print(f"Error closing serial port: {e}")
            self.ser = None
            self.serial_thread = None
            self.poll_thread = None
            self.connect_btn.config(text="Connect")
            self.abs_position = (0, 0)
            self.rel_position = (0, 0)
            self.wcs_offset = (0, 0)
            self.last_g92_time = time.time()
            self.update_position_labels()

    def serial_reader(self):
        """Event-based serial data reader with buffer management"""
        while self.connected:
            if self.ser and self.ser.is_open:
                try:
                    # Read all available data
                    data = self.ser.read(self.ser.in_waiting or 1).decode(errors='ignore')
                    if data:
                        self.receive_buffer += data
                        
                        # Process complete messages
                        while '>' in self.receive_buffer or '\n' in self.receive_buffer:
                            # Try to find a complete status message
                            start_idx = self.receive_buffer.find('<')
                            end_idx = self.receive_buffer.find('>')
                            if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                                line = self.receive_buffer[start_idx:end_idx + 1]
                                self.receive_buffer = self.receive_buffer[end_idx + 1:]
                                line = line.strip()
                                if line:
                                    #print(f"Received status: {line}")  # Debug: log received status
                                    self.process_received_line(line)
                            else:
                                # Check for non-status messages (e.g., 'ok', 'error:')
                                if '\n' in self.receive_buffer:
                                    line, self.receive_buffer = self.receive_buffer.split('\n', 1)
                                    line = line.strip()
                                    if line:
                                        if line == "ok" or line.startswith("error:"):
                                            #print(f"Received response: {line}")  # Debug: log ok/error
                                            self.process_received_line(line)
                                        else:
                                            print(f"Ignored incomplete or malformed message: {line}")
                                break
                        
                        # Check for timeout on incomplete data
                        if self.receive_buffer and time.time() - self.last_data_time > 0.1:  # 100ms timeout
                            line = self.receive_buffer.strip()
                            if line and not (line.startswith('<') and line.endswith('>')):
                                print(f"Timeout on incomplete message: {line}")
                            self.receive_buffer = ""
                        
                    self.last_data_time = time.time()  # Update last data reception time
                except Exception as e:
                    print(f"Error reading serial port: {e}")
                    time.sleep(0.01)
            time.sleep(0.001)  # Small delay to prevent CPU overload

    def process_received_line(self, line):
        """Process a complete received line"""
        # Add to response queue for GUI thread processing
        self.response_queue.append(line)
        
        # Handle immediate responses for flow control
        if line == "ok":
            #print(f"Processing ok for line {self.current_line}")  # Debug: log ok processing
            if self.running and not self.paused:
                self.send_next_gcode()
        elif line.startswith("error:"):
            print(f"GRBL error: {line}")
            messagebox.showerror("Error", f"GRBL error: {line}")

    def poll_position(self):
        while self.connected:
            self.send_cmd(STATUS_QUERY, log=False)
            time.sleep(POLL_INTERVAL)

    def process_responses(self):
        while self.response_queue:
            resp = self.response_queue.popleft()
            if resp.startswith("<") and resp.endswith(">"):
                # Process status reports
                status_content = resp[1:-1]  # Remove '<' and '>'
                parts = status_content.split("|")
                for part in parts[1:]:  # Skip state
                    if part.startswith("MPos:"):
                        pos = part[5:].split(",")
                        try:
                            new_abs = (float(pos[0]), float(pos[1]))
                            self.abs_position = new_abs
                            if time.time() - self.last_g92_time >= POLL_INTERVAL:
                                self.rel_position = (new_abs[0] - self.wcs_offset[0], new_abs[1] - self.wcs_offset[1])
                                self.last_sync_time = time.time()
                            self.update_position_labels()
                            self.update_position_marker()
                        except (ValueError, IndexError):
                            print(f"Error parsing MPos data: {part}")
                    elif part.startswith("WCO:"):
                        wco = part[4:].split(",")
                        try:
                            self.wcs_offset = (float(wco[0]), float(wco[1]))
                            self.rel_position = (self.abs_position[0] - self.wcs_offset[0], self.abs_position[1] - self.wcs_offset[1])
                            self.last_sync_time = time.time()
                            self.update_position_labels()
                        except (ValueError, IndexError):
                            print(f"Error parsing WCO data: {part}")
                    # Silently ignore other fields (e.g., FS:, Ov:, A:, state)
            elif resp == "ok":
                # Already handled in process_received_line for flow control
                pass
            elif resp.startswith("error:"):
                # Already handled in process_received_line
                pass
            else:
                print(f"Other response: {resp}")

    def update_relative_position(self, cmd):
        cmds = cmd.upper().split()
        dx = dy = 0
        if cmd == HOME_CMD:
            self.abs_position = (0, 0)
            self.rel_position = (0, 0)
            self.wcs_offset = (0, 0)
            self.last_g92_time = time.time()
        elif cmd == SET_ZERO_CMD:
            self.wcs_offset = self.abs_position
            self.rel_position = (0, 0)
            self.last_g92_time = time.time()
        elif cmd == RETURN_ZERO_CMD:
            self.rel_position = (0, 0)
            self.abs_position = self.wcs_offset
        else:
            for c in cmds:
                if c.startswith("X"):
                    try:
                        dx = float(c[1:])
                    except ValueError:
                        print(f"Error parsing X value in command: {c}")
                        pass
                elif c.startswith("Y"):
                    try:
                        dy = float(c[1:])
                    except ValueError:
                        print(f"Error parsing Y value in command: {c}")
                        pass
                elif c.startswith("G92"):
                    if "X" in cmd or "Y" in cmd:
                        self.wcs_offset = (self.abs_position[0] - dx, self.abs_position[1] - dy)
                        self.rel_position = (dx, dy)
                        self.last_g92_time = time.time()
            if cmd.startswith("G91"):
                self.rel_position = (self.rel_position[0] + dx, self.rel_position[1] + dy)
                self.abs_position = (self.abs_position[0] + dx, self.abs_position[1] + dy)
            elif cmd.startswith("G90"):
                self.rel_position = (dx, dy)
                self.abs_position = (dx + self.wcs_offset[0], dy + self.wcs_offset[1])
        self.update_position_labels()

    def analyze_gcode(self, lines, fix_idle=False):
        self.min_x = self.min_y = float("inf")
        self.max_x = self.max_y = float("-inf")
        self.max_working_speed = 0.0
        self.max_idle_speed = 0.0
        self.max_power = 0.0
        has_g1_idle = False
        in_idle = False
        current_x, current_y = 0.0, 0.0
        fixed_lines = [] if fix_idle else None
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("%") or stripped.startswith(";"):
                if fix_idle:
                    fixed_lines.append(line)
                continue
            upper = stripped.upper()
            params = self.parse_params(line)
            new_x = params.get('X', current_x)
            new_y = params.get('Y', current_y)
            
            if upper.startswith("M5"):
                in_idle = True
            elif upper.startswith("M3") or upper.startswith("M4"):
                in_idle = False
            if 'F' in params:
                f_val = params['F']
                if upper.startswith('G0') or (in_idle and upper.startswith('G1')):
                    self.max_idle_speed = max(self.max_idle_speed, f_val)
                elif upper.startswith('G1'):
                    self.max_working_speed = max(self.max_working_speed, f_val)
            if 'S' in params:
                self.max_power = max(self.max_power, params['S'])
            if new_x != current_x or new_y != current_y:
                self.min_x = min(self.min_x, min(current_x, new_x))
                self.max_x = max(self.max_x, max(current_x, new_x))
                self.min_y = min(self.min_y, min(current_y, new_y))
                self.max_y = max(self.max_y, max(current_y, new_y))
            if in_idle and G1_IDLE_RE.match(upper):
                has_g1_idle = True
                if fix_idle:
                    new_line = re.sub(r'^(G1|G01)\b', 'G0', line, flags=re.IGNORECASE)
                    fixed_lines.append(new_line)
                    continue
            if fix_idle:
                fixed_lines.append(line)
            current_x, current_y = new_x, new_y
        
        return has_g1_idle, fixed_lines if fix_idle else lines

    def load_file(self):
        file_path = filedialog.askopenfilename(initialdir=self.last_open_dir, filetypes=[("GCode", "*.gcode *.nc")])
        if file_path:
            self.last_open_dir = os.path.dirname(file_path)
            self.save_config()
            
            # Check file size before reading
            try:
                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_SIZE:
                    messagebox.showwarning(
                        "Warning: File Too Large",
                        f"The G-code file size is {file_size / (1024 * 1024):.2f} MB, "
                        f"which exceeds the limit of {MAX_FILE_SIZE / (1024 * 1024):.2f} MB. "
                        "Loading cancelled to prevent performance issues."
                    )
                    return
            except Exception as e:
                messagebox.showerror("Error", f"Failed to check file size: {e}")
                return
            
            # Read file with line limit check
            input_lines = []
            try:
                with open(file_path, "r") as f:
                    for i, line in enumerate(f, 1):
                        input_lines.append(line.rstrip('\n'))
                        if i > MAX_GCODE_LINES:
                            messagebox.showwarning(
                                "Warning: Too Many Lines",
                                f"The G-code file has more than {MAX_GCODE_LINES} lines. "
                                "Loading cancelled to prevent performance issues."
                            )
                            return
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read G-code file: {e}")
                return
            
            # Remove comments (semicolon and parenthetical) and empty lines
            cleaned_lines = []
            try:
                for line in input_lines:
                    line = re.sub(r'\(.*?\)', '', line)
                    line = re.split(r';', line)[0]
                    line = line.strip()
                    if line:
                        cleaned_lines.append(line)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to process G-code comments: {e}")
                return
            
            # Check if the number of cleaned lines exceeds the limit
            if len(cleaned_lines) > MAX_GCODE_LINES:
                messagebox.showwarning(
                    "Warning: File Too Large",
                    f"The G-code file has {len(cleaned_lines)} lines, which exceeds the limit of {MAX_GCODE_LINES}. "
                    "Loading cancelled to prevent performance issues."
                )
                return
            
            has_g1_idle, lines = self.analyze_gcode(cleaned_lines)
            if has_g1_idle:
                response = messagebox.askyesno(
                    "Warning",
                    "The G-code uses G1 for idle moves in laser mode (M5 ... G1 ... M3). "
                    "This is non-standard and may cause issues. "
                    "Would you like to fix it by replacing G1 with G0 for idle moves and save as a new file?"
                )
                if response:
                    try:
                        _, fixed_lines = self.analyze_gcode(cleaned_lines, fix_idle=True)
                        program_dir = os.path.dirname(os.path.abspath(__file__))
                        i = 1
                        while os.path.exists(os.path.join(program_dir, f"temp_{i}.gcode")):
                            i += 1
                        temp_file = os.path.join(program_dir, f"temp_{i}.gcode")
                        with open(temp_file, 'w') as f:
                            for line in fixed_lines:
                                f.write(line + '\n')
                        self.temp_files.append(temp_file)
                        initialdir = self.last_save_dir if self.last_save_dir else self.last_open_dir
                        save_path = filedialog.asksaveasfilename(
                            initialdir=initialdir,
                            filetypes=[("GCode", "*.gcode *.nc")],
                            defaultextension=".gcode",
                            initialfile="fixed_" + os.path.basename(file_path)
                        )
                        if save_path:
                            shutil.copy(temp_file, save_path)
                            self.last_save_dir = os.path.dirname(save_path)
                            self.save_config()
                            file_path = save_path
                        else:
                            file_path = temp_file
                        with open(file_path, "r") as f:
                            lines = [line.rstrip('\n') for line in f]
                        cleaned_lines = []
                        for line in lines:
                            line = re.sub(r'\(.*?\)', '', line)
                            line = re.split(r';', line)[0]
                            line = line.strip()
                            if line:
                                cleaned_lines.append(line)
                    except Exception as e:
                        print(f"Error processing G1 idle fix: {e}")
                        messagebox.showerror("Error", f"Failed to fix G1 idle moves: {e}")
                        return
            
            self.current_file = file_path
            self.gcode_lines = cleaned_lines
            self.current_line = 0
            self.sent_lines.clear()
            self.gcode_loaded = True
            try:
                self.draw_gcode()
                self.update_file_info()
            except Exception as e:
                print(f"Error updating G-code display: {e}")
                messagebox.showerror("Error", f"Failed to update G-code display: {e}")

    def save_file(self):
        if not self.gcode_loaded or not self.current_file:
            return
        initialdir = self.last_save_dir if self.last_save_dir else self.last_open_dir
        file_path = filedialog.asksaveasfilename(initialdir=initialdir, filetypes=[("GCode", "*.gcode *.nc")])
        if file_path:
            try:
                shutil.copy(self.current_file, file_path)
                self.last_save_dir = os.path.dirname(file_path)
                self.file_name_label.config(text=f"File Name: {os.path.basename(file_path)}")
                self.save_config()
            except Exception as e:
                print(f"Error saving G-code file: {e}")
                messagebox.showerror("Error", f"Failed to save G-code file: {e}")

    def send_cmd(self, cmd, log=True):
        if self.connected and self.ser and self.ser.is_open:
            try:
                self.ser.write((cmd + "\n").encode())
                if log and cmd != STATUS_QUERY:
                    self.sent_commands.append(cmd)
                    self.cmd_monitor.insert(tk.END, cmd + "\n")
                    self.cmd_monitor.see(tk.END)
                    #print(f"Sent command: {cmd}")  # Debug: log sent command
                    if cmd.startswith(("G0 ", "G1 ", "G91", "G90", "G92", "$H", RETURN_ZERO_CMD)):
                        self.update_relative_position(cmd)
                        if cmd.startswith("G92"):
                            self.last_g92_time = time.time()
            except Exception as e:
                print(f"Error sending command: {e}")

    def jog(self, cmd_template):
        if not self.connected:
            return
        if cmd_template == "ZERO":
            self.return_to_zero()
        else:
            try:
                step = float(self.step_var.get()) * float(self.multiplier_var.get())
                direction = cmd_template.format(step, step)
            except Exception:
                try:
                    step = float(self.step_var.get()) * float(self.multiplier_var.get())
                    direction = cmd_template.format(step)
                except Exception as e:
                    print(f"Error formatting jog command: {e}")
                    return
            self.send_cmd(JOG_CMD.format(direction))

    def home(self):
        self.send_cmd(HOME_CMD)

    def unlock(self):
        self.send_cmd(UNLOCK_CMD)

    def reset(self):
        self.send_cmd(SOFT_RESET)
        self.rel_position = (0, 0)
        self.abs_position = (0, 0)
        self.wcs_offset = (0, 0)
        self.last_g92_time = time.time()
        self.update_position_labels()

    def set_zero(self):
        self.send_cmd(SET_ZERO_CMD)
        self.wcs_offset = self.abs_position
        self.rel_position = (0, 0)
        self.last_g92_time = time.time()
        self.update_position_labels()

    def return_to_zero(self):
        self.send_cmd(RETURN_ZERO_CMD)

    def toggle_pause_resume(self):
        if self.running:
            if self.paused:
                self.resume_gcode()
                self.pause_btn.config(text="Pause")
            else:
                self.pause_gcode()
                self.pause_btn.config(text="Resume")

    def start_gcode(self):
        if not self.connected or not self.gcode_lines:
            print("Warning: Not connected or no G-code loaded")
            messagebox.showwarning("Warning", "Not connected or no G-code loaded")
            return
        self.running = True
        self.paused = False
        self.current_line = 0
        self.sent_lines.clear()
        self.pause_btn.config(text="Pause", state=tk.NORMAL)
        print("Starting G-code execution")  # Debug: log start
        self.send_next_gcode()

    def pause_gcode(self):
        if self.running:
            self.paused = True
            self.send_cmd(PAUSE_CMD)
            print("G-code paused")  # Debug: log pause

    def resume_gcode(self):
        self.paused = False
        self.send_cmd(RESUME_CMD)
        print("Resuming G-code execution")  # Debug: log resume
        self.send_next_gcode()

    def stop_gcode(self):
        self.running = False
        self.paused = False
        self.current_line = 0
        self.pause_btn.config(text="Pause", state=tk.DISABLED)
        self.send_cmd(SOFT_RESET)
        print("G-code stopped")  # Debug: log stop

    def send_next_gcode(self):
        if not self.running or self.paused or self.current_line >= len(self.gcode_lines):
            if self.current_line >= len(self.gcode_lines):
                self.running = False
                self.pause_btn.config(state=tk.DISABLED)
                print("G-code execution completed")  # Debug: log completion
            return
            
        line = self.gcode_lines[self.current_line]
        #print(f"Sending G-code line {self.current_line}: {line}")  # Debug: log line being sent
        self.send_cmd(line)
        self.sent_lines.add(self.current_line)
        
        if self.current_line in self.line_to_path:
            idx = self.line_to_path[self.current_line]
            if 0 <= idx < len(self.paths):
                try:
                    self.canvas.itemconfig(self.paths[idx], fill="red")
                except Exception:
                    print(f"Error updating canvas path for line {self.current_line}")
                    pass
        self.current_line += 1

    def send_custom_cmd(self):
        cmd = self.cmd_entry.get()
        if cmd:
            self.last_command.set(cmd)
            self.save_config()
            self.send_cmd(cmd)
            self.cmd_entry.delete(0, tk.END)

    def process_with_script(self, script_name, *args):
        if not self.gcode_loaded or not self.current_file:
            return
        program_dir = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(program_dir, script_name)
        i = 1
        while os.path.exists(os.path.join(program_dir, f"temp_{i}.gcode")):
            i += 1
        temp_file = os.path.join(program_dir, f"temp_{i}.gcode")
        try:
            with open(temp_file, 'w') as f:
                for line in self.gcode_lines:
                    f.write(line + '\n')
            self.temp_files.append(temp_file)
            cmd = f"{sys.executable} {script} {temp_file} {' '.join(map(str, args))} {temp_file}"
            os.system(cmd)
            with open(temp_file, 'r') as f:
                lines = [line.rstrip('\n') for line in f]
            cleaned_lines = []
            for line in lines:
                line = re.sub(r'\(.*?\)', '', line)
                line = re.split(r';', line)[0]
                line = line.strip()
                if line:
                    cleaned_lines.append(line)
            self.gcode_lines = cleaned_lines
            self.current_file = temp_file
            self.gcode_loaded = True
            self.draw_gcode()
            self.update_file_info()
            self.save_config()  # Save config after processing
        except Exception as e:
            print(f"Error processing G-code with script {script_name}: {e}")
            messagebox.showerror("Error", f"Failed to process G-code: {e}")

    def run_fix(self):
        power = self.power_fix_var.get()
        try:
            power_val = float(power)
            if power_val <= 0:
                raise ValueError
        except ValueError:
            print("Error: Power must be a positive number")
            messagebox.showerror("Error", "Power must be a positive number")
            return
        self.process_with_script(FIX_POWER_SCRIPT, power)
        self.save_config()

    def run_scale(self):
        max_x = self.max_x_var.get()
        max_y = self.max_y_var.get()
        try:
            x_val = float(max_x)
            y_val = float(max_y)
            if x_val <= 0 or y_val <= 0:
                raise ValueError
        except ValueError:
            print("Error: Target sizes must be positive numbers")
            messagebox.showerror("Error", "Target sizes must be positive numbers")
            return
        self.process_with_script(SCALE_GCODE_SCRIPT, max_x, max_y)
        self.save_config()

    def run_optimize(self):
        opt_level = self.opt_level_var.get()
        try:
            level_val = int(opt_level)
            if level_val not in (0, 1, 2):
                raise ValueError
        except ValueError:
            print("Error: Optimization level must be 0, 1, or 2")
            messagebox.showerror("Error", "Optimization level must be 0, 1, or 2")
            return
        self.process_with_script(OPTIMIZE_GCODE_SCRIPT, "--level", opt_level)
        self.save_config()

    def run_adjust_speed(self):
        max_speed = self.max_speed_var.get()
        max_idle_speed = self.max_idle_speed_var.get()
        try:
            speed_val = float(max_speed)
            idle_speed_val = float(max_idle_speed)
            if speed_val <= 0 or idle_speed_val <= 0:
                raise ValueError
        except ValueError:
            print("Error: Max working and idle speeds must be positive numbers")
            messagebox.showerror("Error", "Max working and idle speeds must be positive numbers")
            return
        self.process_with_script(ADJUST_SPEED_SCRIPT, max_speed, max_idle_speed)
        self.save_config()

    def run_adjust_power(self):
        max_power = self.max_power_var.get()
        try:
            power_val = int(max_power)
            if power_val <= 0:
                raise ValueError
        except ValueError:
            print("Error: Max power must be a positive integer")
            messagebox.showerror("Error", "Max power must be a positive integer")
            return
        self.process_with_script(ADJUST_POWER_SCRIPT, max_power)
        self.save_config()

    def update(self):
        self.process_responses()
        if self.connected and time.time() - self.last_sync_time >= POLL_INTERVAL:
            self.send_cmd(STATUS_QUERY, log=False)
        self.after(100, self.update)

    def quit_app(self):
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    print(f"Error removing temporary file {temp_file}: {e}")
        self.save_config()
        self.quit()

if __name__ == "__main__":
    app = GRBLController()
    app.last_data_time = time.time()  # Initialize last data time
    app.after(100, app.update)
    app.mainloop()

