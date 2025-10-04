import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageEnhance
import json
import serial
import serial.tools.list_ports
import threading
import time
from queue import Queue
import numpy as np
import io

CMD_BUFF_DEPTH = 10
USB_PORT = '/dev/ttyUSB0'
BAUDRATE = 115200
WORK_SPEED = 2500
IDLE_SPEED = 2500
MAX_POWER_PERCENT = 50
MIN_POWER_PERCENT = 5
LASER_MAX = 1000
PIXEL_SIZE_MM = 0.1
Y_STEP_MM = 0.1
ACCEL_PAD_MM = 3.0
LOG_FILE = 'log.txt'
SERIAL_SLEEP = 0.0001
LOG_ENABLED = False
SETTINGS_FILE = f"{os.path.splitext(os.path.basename(__file__))[0]}.json"
SIDE_PANEL_WIDTH = 250
DEFAULT_WORK_X = 100.0
DEFAULT_WORK_Y = 100.0
DEFAULT_MIN_POWER = 5
DEFAULT_MAX_POWER = 90
DEFAULT_BURN_SPEED = 2500
DEFAULT_LAST_DIR = os.getcwd()
JOG_CMD = "G91 {}"
HOME_CMD = "$H"
UNLOCK_CMD = "$X"
SET_ZERO_CMD = "G92 X0 Y0"
RETURN_ZERO_CMD = "G90 X0 Y0"
SOFT_RESET = "\x18"
PAUSE_CMD = "!"
RESUME_CMD = "~"
DEFAULT_TEST_WORK_X = 100.0
DEFAULT_TEST_WORK_Y = 100.0
DEFAULT_TEST_X_STEPS = 10
DEFAULT_TEST_MIN_POWER = 5
DEFAULT_TEST_MAX_POWER = 90
DEFAULT_TEST_Y_STEPS = 10
DEFAULT_TEST_MIN_SPEED = 800
DEFAULT_TEST_MAX_SPEED = 2500
TEST_SQUARE_FRACTION = 0.8
TEST_SEPARATOR_FRACTION = 0.2

class GrblWindowTester:
    def __init__(self, port=USB_PORT, baudrate=BAUDRATE, min_power_percent=MIN_POWER_PERCENT, max_power_percent=MAX_POWER_PERCENT, work_speed=WORK_SPEED, image_array=None, test_params=None):
        # Initializes the GRBL window tester with serial connection and engraving parameters
        self.ser = serial.Serial(port, baudrate, timeout=0, write_timeout=0)
        self.rx_buffer = bytearray()
        self.window_size = CMD_BUFF_DEPTH
        self.pending_commands = 0
        self.total_sent = 0
        self.total_ok = 0
        self.command_queue = Queue()
        self.send_allowed = False
        self.running = True
        self.paused = False
        self.ok_event = threading.Event()
        self.laser_map = self._create_laser_map(min_power_percent, max_power_percent) if image_array is not None else None
        self.left_pad_mm = ACCEL_PAD_MM
        self.right_pad_mm = ACCEL_PAD_MM
        self.current_x = 0.0
        self.log_file = open(os.path.join(os.path.dirname(__file__), LOG_FILE), 'w', encoding='utf-8') if LOG_ENABLED else None
        self.work_speed = work_speed
        self.image_array = image_array
        self.test_params = test_params

    def _create_laser_map(self, min_power_percent, max_power_percent):
        # Creates a laser power mapping for image engraving
        max_power = int(LASER_MAX * max_power_percent / 100)
        min_power = int(LASER_MAX * min_power_percent / 100)
        laser_map = np.zeros(256, dtype=int)
        laser_map[:255] = np.linspace(max_power, min_power, 255, dtype=int)
        laser_map[255] = 0
        return laser_map

    def _load_and_preprocess_image(self, pic_file=None):
        # Loads and preprocesses an image for engraving
        try:
            if pic_file and isinstance(pic_file, str):
                img = Image.open(pic_file)
                if img.mode != 'L':
                    img = img.convert('L')
                img_array = np.flipud(np.array(img, dtype=np.uint8))
                return img_array
            elif self.image_array is not None:
                return self.image_array
            else:
                return None
        except Exception as e:
            print(f"Image load error: {e}")
            return None

    def _execute(self):
        # Executes queued commands until completion or interruption
        self.send_allowed = True
        while (not self.command_queue.empty() or self.pending_commands > 0) and self.running:
            if self.ok_event.wait(timeout=0.1):
                self.ok_event.clear()
        self.send_allowed = False

    def _initialize_grbl(self):
        # Initializes GRBL with configuration commands
        init_cmds = [
            b'$120=600\n',
            b'$121=600\n',
            b'G91\n'
        ]
        for cmd in init_cmds:
            if not self.running:
                return
            if LOG_ENABLED and self.log_file:
                self.log_file.write(f"{cmd.decode('utf-8', errors='ignore').strip()}\n")
                self.log_file.flush()
            self.command_queue.put(cmd)
        self._execute()

    def _engrave_row(self, row, row_number, total_rows, direction, image_width_mm):
        # Engraves a single row of the image
        if not self.running:
            return
        
        if direction == 1:
            row_data = row
            pad_start_mm = self.left_pad_mm
            pad_end_mm = self.right_pad_mm
            x_dir = 1
        else:
            row_data = row[::-1]
            pad_start_mm = self.right_pad_mm
            pad_end_mm = self.left_pad_mm
            x_dir = -1
        
        mapped_row = self.laser_map[row_data]
        
        non_zero_indices = np.argwhere(mapped_row != 0)
        if len(non_zero_indices) == 0:
            return
            
        trim_start_idx = non_zero_indices[0][0]
        trim_end_idx = non_zero_indices[-1][0] + 1
        trimmed_row = mapped_row[trim_start_idx:trim_end_idx]
        
        trim_width_mm = (trim_end_idx - trim_start_idx) * PIXEL_SIZE_MM
        
        if direction == 1:
            effective_start_mm = trim_start_idx * PIXEL_SIZE_MM
            required_start_mm = effective_start_mm - pad_start_mm
        else:
            effective_start_mm = image_width_mm - trim_start_idx * PIXEL_SIZE_MM - trim_width_mm
            required_start_mm = effective_start_mm + trim_width_mm + pad_start_mm
        
        cmds = []
        
        delta_to_start = required_start_mm - self.current_x
        if abs(delta_to_start) > 0.01:
            cmds.append(f'G1 X{delta_to_start:.1f} F{IDLE_SPEED}\n'.encode())
        
        cmds.append(f'F{self.work_speed}\n'.encode())
        cmds.append(b'M3 S0\n')
        if pad_start_mm > 0:
            cmds.append(f'G1 X{(x_dir * pad_start_mm):.1f} S0\n'.encode())
        
        i = 0
        n = len(trimmed_row)
        while i < n and self.running:
            s = trimmed_row[i]
            start = i
            while i < n and trimmed_row[i] == s and self.running:
                i += 1
            length = i - start
            dist = length * PIXEL_SIZE_MM
            cmds.append(f'G1 X{(x_dir * dist):.1f} S{s}\n'.encode())
        
        if pad_end_mm > 0 and self.running:
            cmds.append(f'G1 X{(x_dir * pad_end_mm):.1f} S0\n'.encode())
        
        if self.running:
            cmds.append(b'M5\n')
        
        if LOG_ENABLED and self.log_file:
            for cmd in cmds:
                self.log_file.write(f"{cmd.decode('utf-8', errors='ignore').strip()}\n")
            self.log_file.flush()
        
        for cmd in cmds:
            if not self.running:
                break
            self.command_queue.put(cmd)
        
        if not self.running:
            return
            
        print(f"Row {row_number}/{total_rows}, commands: {len(cmds)}")
        
        if abs(delta_to_start) > 0.01:
            self.current_x += delta_to_start
        engrave_delta = x_dir * (pad_start_mm + trim_width_mm + pad_end_mm)
        self.current_x += engrave_delta
        
        self._execute()

        while self.paused and self.running:
            time.sleep(0.1)
        if not self.running:
            raise Exception("Stopped")

    def _engrave_test_row(self, powers, square_mm, sep_mm, direction, actual_width_mm):
        # Engraves a test row with specified power levels
        if not self.running:
            return
        
        offset = ACCEL_PAD_MM
        
        if direction == 1:
            row_powers = powers
            pad_start_mm = self.left_pad_mm
            pad_end_mm = self.right_pad_mm
            x_dir = 1
            effective_start_mm = offset
            required_start_mm = effective_start_mm - pad_start_mm
        else:
            row_powers = powers[::-1]
            pad_start_mm = self.right_pad_mm
            pad_end_mm = self.left_pad_mm
            x_dir = -1
            effective_start_mm = offset + actual_width_mm
            required_start_mm = effective_start_mm + pad_start_mm
        
        cmds = []
        
        delta_to_start = required_start_mm - self.current_x
        if abs(delta_to_start) > 0.01:
            cmds.append(f'G1 X{delta_to_start:.1f} F{IDLE_SPEED}\n'.encode())
        
        cmds.append(f'F{self.work_speed}\n'.encode())
        cmds.append(b'M3 S0\n')
        if pad_start_mm > 0:
            cmds.append(f'G1 X{(x_dir * pad_start_mm):.1f} S0\n'.encode())
        
        n = len(row_powers)
        for i in range(n):
            s = row_powers[i]
            dist = square_mm
            cmds.append(f'G1 X{(x_dir * dist):.1f} S{s}\n'.encode())
            if i < n - 1:
                sep_dist = sep_mm
                cmds.append(f'G1 X{(x_dir * sep_dist):.1f} S0\n'.encode())
        
        if pad_end_mm > 0:
            cmds.append(f'G1 X{(x_dir * pad_end_mm):.1f} S0\n'.encode())
        
        cmds.append(b'M5\n')
        
        if LOG_ENABLED and self.log_file:
            for cmd in cmds:
                self.log_file.write(f"{cmd.decode('utf-8', errors='ignore').strip()}\n")
            self.log_file.flush()
        
        for cmd in cmds:
            if not self.running:
                break
            self.command_queue.put(cmd)
        
        if not self.running:
            return
        
        print(f"Engraved test row, direction: {direction}, commands: {len(cmds)}")
        
        if abs(delta_to_start) > 0.01:
            self.current_x += delta_to_start
        engrave_delta = x_dir * (pad_start_mm + n * square_mm + (n - 1) * sep_mm + pad_end_mm)
        self.current_x += engrave_delta
        
        self._execute()

        while self.paused and self.running:
            time.sleep(0.1)
        if not self.running:
            raise Exception("Stopped")

    def rx_interrupt_handler(self):
        # Handles incoming serial data and processes 'ok' responses
        while self.running:
            if self.ser.in_waiting > 0:
                try:
                    data = self.ser.read(self.ser.in_waiting)
                    self.rx_buffer.extend(data)
                    while b'ok\r' in self.rx_buffer:
                        ok_pos = self.rx_buffer.find(b'ok\r')
                        self.rx_buffer = self.rx_buffer[ok_pos + 3:]
                        if self.pending_commands > 0:
                            self.pending_commands -= 1
                            self.total_ok += 1
                            self.ok_event.set()
                except Exception as e:
                    if self.running:
                        print(f"Error in rx_interrupt_handler: {e}")
            time.sleep(SERIAL_SLEEP)

    def tx_interrupt_handler(self):
        # Sends commands from the queue when allowed
        while self.running:
            if (self.send_allowed and
                self.pending_commands < self.window_size and
                not self.command_queue.empty() and
                self.ser.out_waiting == 0 and
                self.running):
                cmd = self.command_queue.get()
                try:
                    self.ser.write(cmd)
                    self.pending_commands += 1
                    self.total_sent += 1
                except Exception as e:
                    if self.running:
                        print(f"Error sending command: {e}")
            time.sleep(SERIAL_SLEEP)

    def start(self, pic_file=None):
        # Starts the image engraving process
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(0.1)
        
        self.rx_thread = threading.Thread(target=self.rx_interrupt_handler)
        self.tx_thread = threading.Thread(target=self.tx_interrupt_handler)
        self.rx_thread.daemon = True
        self.tx_thread.daemon = True
        self.rx_thread.start()
        self.tx_thread.start()

        img = self._load_and_preprocess_image(pic_file)
        if img is None:
            self.stop()
            return        
        height, width = img.shape
        image_width_mm = width * PIXEL_SIZE_MM          
        self.is_empty = [np.all(self.laser_map[row] == 0) for row in img]
        
        self._initialize_grbl()
        
        direction = 1
        y = 0
        try:
            while y < height and self.running:
                if not self.running:
                    break
                
                if self.is_empty[y]:
                    empty_count = 1
                    while y + empty_count < height and self.is_empty[y + empty_count] and self.running:
                        empty_count += 1
                    shift_mm = empty_count * Y_STEP_MM
                    cmd_str = f'G1 Y{shift_mm:.1f} F{IDLE_SPEED}\n'
                    cmd = cmd_str.encode()
                    print(f"Skipped {empty_count} empty rows (from {y+1} to {y+empty_count})")
                    if LOG_ENABLED and self.log_file:
                        self.log_file.write(cmd_str)
                        self.log_file.flush()
                    self.command_queue.put(cmd)
                    self._execute()
                    if empty_count % 2 == 1:
                        direction *= -1
                    print(f"Y shift by {shift_mm:.1f} mm.")
                    y += empty_count
                else:
                    self._engrave_row(img[y], y + 1, height, direction, image_width_mm)
                    direction *= -1
                    y += 1
                    if y < height and self.running:
                        cmd_str = f'G1 Y{Y_STEP_MM:.1f} F{IDLE_SPEED}\n'
                        cmd = cmd_str.encode()
                        if LOG_ENABLED and self.log_file:
                            self.log_file.write(cmd_str)
                            self.log_file.flush()
                        self.command_queue.put(cmd)
                        self._execute()
                
                while self.paused and self.running:
                    time.sleep(0.1)
            
            if self.running:
                return_dist = -self.current_x
                if abs(return_dist) > 0.01:
                    cmd_str = f'G1 X{return_dist:.1f} F{IDLE_SPEED}\n'
                    cmd = cmd_str.encode()
                    print("Returning to initial X position")
                    if LOG_ENABLED and self.log_file:
                        self.log_file.write(cmd_str)
                        self.log_file.flush()
                    self.command_queue.put(cmd)
                    self._execute()
                
                print("Image engraving completed.")
        except Exception as e:
            print(f"Engraving stopped: {e}")
        finally:
            self.stop()

    def start_test(self):
        # Starts the test pattern engraving process
        if self.test_params is None:
            raise ValueError("No test parameters provided")
        
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(0.1)
        
        self.rx_thread = threading.Thread(target=self.rx_interrupt_handler)
        self.tx_thread = threading.Thread(target=self.tx_interrupt_handler)
        self.rx_thread.daemon = True
        self.tx_thread.daemon = True
        self.rx_thread.start()
        self.tx_thread.start()
        
        work_x = self.test_params['work_x']
        work_y = self.test_params['work_y']
        nx = self.test_params['x_steps']
        min_power = self.test_params['min_power']
        max_power = self.test_params['max_power']
        ny = self.test_params['y_steps']
        min_speed = self.test_params['min_speed']
        max_speed = self.test_params['max_speed']
        
        cell_x = work_x / nx
        square_x = TEST_SQUARE_FRACTION * cell_x
        sep_x = TEST_SEPARATOR_FRACTION * cell_x
        cell_y = work_y / ny
        square_y = TEST_SQUARE_FRACTION * cell_y
        sep_y = TEST_SEPARATOR_FRACTION * cell_y
        num_lines = 2 * int(square_y / Y_STEP_MM / 2)
        actual_width = nx * square_x + (nx - 1) * sep_x
        
        powers_percent = np.linspace(min_power, max_power, nx)
        powers = np.round(powers_percent / 100 * LASER_MAX).astype(int)
        speeds = np.round(np.linspace(max_speed, min_speed, ny)).astype(int)
        
        self._initialize_grbl()
        
        direction = 1
        y_position = 0
        try:
            for iy in range(ny):
                if not self.running:
                    break
                self.work_speed = speeds[iy]
                for iline in range(num_lines):
                    if not self.running:
                        break
                    self._engrave_test_row(powers, square_x, sep_x, direction, actual_width)
                    direction *= -1
                    if iline < num_lines - 1:
                        cmd_str = f'G1 Y{Y_STEP_MM:.1f} F{IDLE_SPEED}\n'
                        cmd = cmd_str.encode()
                        if LOG_ENABLED and self.log_file:
                            self.log_file.write(cmd_str)
                            self.log_file.flush()
                        self.command_queue.put(cmd)
                        self._execute()
                        y_position += Y_STEP_MM
                    while self.paused and self.running:
                        time.sleep(0.1)
                if not self.running:
                    break
                if iy < ny - 1:
                    delta_y = square_y + sep_y - (num_lines - 1) * Y_STEP_MM
                    cmd_str = f'G1 Y{delta_y:.1f} F{IDLE_SPEED}\n'
                    cmd = cmd_str.encode()
                    if LOG_ENABLED and self.log_file:
                        self.log_file.write(cmd_str)
                        self.log_file.flush()
                    self.command_queue.put(cmd)
                    self._execute()
                    y_position += delta_y
            
            if self.running:
                return_dist = -self.current_x
                if abs(return_dist) > 0.01:
                    cmd_str = f'G1 X{return_dist:.1f} F{IDLE_SPEED}\n'
                    cmd = cmd_str.encode()
                    print("Returning to initial X position")
                    if LOG_ENABLED and self.log_file:
                        self.log_file.write(cmd_str)
                        self.log_file.flush()
                    self.command_queue.put(cmd)
                    self._execute()
                
                print("Test engraving completed.")
        except Exception as e:
            print(f"Test engraving stopped: {e}")
        finally:
            self.stop()

    def stop(self):
        # Stops the engraving process and closes resources
        if not self.running:
            return
            
        print("\nInitiating shutdown...")
        self.running = False
        self.send_allowed = False
        self.ok_event.set()
        
        while not self.command_queue.empty():
            try:
                self.command_queue.get_nowait()
            except:
                pass
        
        timeout = 2.0
        start_time = time.time()
        while self.pending_commands > 0 and (time.time() - start_time) < timeout:
            print(f"Waiting for completion: {self.pending_commands} commands in progress")
            time.sleep(0.1)
        
        if self.ser.is_open:
            try:
                self.ser.flush()
                self.ser.close()
                print("Serial port closed")
            except Exception as e:
                print(f"Error closing port: {e}")
        if LOG_ENABLED and self.log_file:
            try:
                self.log_file.close()
                print("Log file closed")
            except Exception as e:
                print(f"Error closing log file: {e}")
        
        time.sleep(0.5)
        print("Program terminated")

class ImGlaserApp:
    def __init__(self, root):
        # Initializes the main application window and settings
        self.root = root
        self.root.title("imGlaser")
        self.root.geometry("800x600")

        self.settings = self.load_settings()

        self.work_x = tk.DoubleVar(value=self.settings.get('work_x', DEFAULT_WORK_X))
        self.work_y = tk.DoubleVar(value=self.settings.get('work_y', DEFAULT_WORK_Y))
        self.min_power = tk.IntVar(value=self.settings.get('min_power', DEFAULT_MIN_POWER))
        self.max_power = tk.IntVar(value=self.settings.get('max_power', DEFAULT_MAX_POWER))
        self.burn_speed = tk.IntVar(value=self.settings.get('burn_speed', DEFAULT_BURN_SPEED))
        self.step_var = tk.StringVar(value=self.settings.get('step', '1'))
        self.multiplier_var = tk.StringVar(value=self.settings.get('multiplier', '1'))
        self.last_dir = self.settings.get('last_dir', DEFAULT_LAST_DIR)
        self.test_work_x = tk.DoubleVar(value=self.settings.get('test_work_x', DEFAULT_TEST_WORK_X))
        self.test_work_y = tk.DoubleVar(value=self.settings.get('test_work_y', DEFAULT_TEST_WORK_Y))
        self.test_x_steps = tk.IntVar(value=self.settings.get('test_x_steps', DEFAULT_TEST_X_STEPS))
        self.test_min_power = tk.IntVar(value=self.settings.get('test_min_power', DEFAULT_TEST_MIN_POWER))
        self.test_max_power = tk.IntVar(value=self.settings.get('test_max_power', DEFAULT_TEST_MAX_POWER))
        self.test_y_steps = tk.IntVar(value=self.settings.get('test_y_steps', DEFAULT_TEST_Y_STEPS))
        self.test_min_speed = tk.IntVar(value=self.settings.get('test_min_speed', DEFAULT_TEST_MIN_SPEED))
        self.test_max_speed = tk.IntVar(value=self.settings.get('test_max_speed', DEFAULT_TEST_MAX_SPEED))

        self.connected = False
        self.ser = None
        self.tester = None
        self.base_image = None
        self.processed_image = None
        self.original_photo = None
        self.pic_file = None
        self.image_array = None
        self.image_loaded = False
        self.current_filename = None
        self.original_image_info = None
        self.converted_image_info = None
        self.work_area_edit_mode = False

        for var in [self.work_x, self.work_y, self.min_power, self.max_power, self.burn_speed,
                    self.step_var, self.multiplier_var, self.test_work_x, self.test_work_y,
                    self.test_x_steps, self.test_min_power, self.test_max_power,
                    self.test_y_steps, self.test_min_speed, self.test_max_speed]:
            var.trace_add('write', self.save_settings)

        self.menu = tk.Menu(self.root)
        self.file_menu = tk.Menu(self.menu, tearoff=0)
        self.file_menu.add_command(label="Load Image", command=self.load_image)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.exit_app)
        self.menu.add_cascade(label="File", menu=self.file_menu)
        self.root.config(menu=self.menu)

        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        self.left_frame = tk.Frame(self.paned)
        self.top_label = ttk.Label(self.left_frame, text="Image")
        self.top_label.pack(fill=tk.X)
        self.top_canvas = tk.Canvas(self.left_frame, bg='white')
        self.top_canvas.pack(fill=tk.BOTH, expand=True)
        self.paned.add(self.left_frame, weight=1)

        self.right_frame = tk.Frame(self.paned, width=SIDE_PANEL_WIDTH)
        self.right_frame.pack_propagate(False)
        self.paned.add(self.right_frame, weight=0)

        def set_initial_sash():
            if self.root.winfo_width() > 1:
                self.paned.sashpos(0, self.root.winfo_width() - SIDE_PANEL_WIDTH)
            else:
                self.root.after(50, set_initial_sash)
        self.root.update_idletasks()
        set_initial_sash()

        self.notebook = ttk.Notebook(self.right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.manual_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.manual_tab, text="Manual")
        self.setup_manual_tab()

        self.gcode_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.gcode_tab, text="G-code")
        self.setup_gcode_tab()

        self.cmd_monitor = tk.Text(self.right_frame, bg="black", fg="white", wrap=tk.WORD)
        self.cmd_monitor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar = tk.Scrollbar(self.right_frame, orient=tk.VERTICAL, command=self.cmd_monitor.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.cmd_monitor.config(yscrollcommand=scrollbar.set)

        self.top_frame = self.left_frame
        self.top_frame.bind("<Configure>", self.resize_original)

        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)

        self.refresh_ports()
        self.update_start_button_state()
        self.gcode_notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    def on_tab_changed(self, event):
        # Updates start button state when notebook tab changes
        self.update_start_button_state()

    def update_start_button_state(self):
        # Enables/disables start button based on active tab and image availability
        tab_id = self.gcode_notebook.select()
        tab_text = self.gcode_notebook.tab(tab_id, "text")
        if tab_text == "Engraving" and self.image_array is None:
            self.start_btn.config(state=tk.DISABLED)
        else:
            self.start_btn.config(state=tk.NORMAL)

    def setup_manual_tab(self):
        # Sets up the manual control tab UI
        usb_frame = ttk.Frame(self.manual_tab)
        usb_frame.pack(fill=tk.X, pady=5)

        ttk.Label(usb_frame, text="Port:", font=("Arial", 9, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(5, 2))
        self.ports_var = tk.StringVar()
        self.ports_menu = ttk.Combobox(usb_frame, textvariable=self.ports_var, state="readonly")
        self.ports_menu.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(usb_frame, text="Baudrate:", font=("Arial", 9, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(5, 2))
        self.baudrate_var = tk.StringVar(value='115200')
        self.baudrate_menu = ttk.Combobox(usb_frame, textvariable=self.baudrate_var, values=["115200"], state="readonly")
        self.baudrate_menu.pack(fill=tk.X, pady=(0, 5))

        buttons_frame = ttk.Frame(usb_frame)
        buttons_frame.pack(fill=tk.X, pady=5)
        self.refresh_ports_btn = ttk.Button(buttons_frame, text="Refresh", command=self.refresh_ports)
        self.refresh_ports_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.connect_btn = ttk.Button(buttons_frame, text="Connect", command=self.toggle_connect)
        self.connect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        controls_frame = ttk.Frame(self.manual_tab)
        controls_frame.pack(fill=tk.X)
        ttk.Label(controls_frame, text="Step:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=2)
        ttk.Combobox(controls_frame, textvariable=self.step_var, values=["1", "2", "3", "4", "5", "6", "7", "8", "9"], state="readonly", width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(controls_frame, text="Multiplier:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=2)
        ttk.Combobox(controls_frame, textvariable=self.multiplier_var, values=["0.1", "1", "10", "100"], state="readonly", width=5).pack(side=tk.LEFT, padx=2)

        main_jog_frame = ttk.Frame(self.manual_tab)
        main_jog_frame.pack(pady=5, fill=tk.BOTH, expand=True)

        left_sub = ttk.Frame(main_jog_frame)
        left_sub.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        button_frame = ttk.Frame(left_sub)
        button_frame.pack(pady=5)

        directions = [
            ("up-left.png", "X-{} Y{}"),
            ("up.png", "Y{}"),
            ("up-right.png", "X{} Y{}"),
            ("left.png", "X-{}"),
            ("home.png", "ZERO"),
            ("right.png", "X{}"),
            ("down-left.png", "X-{} Y-{}"),
            ("down.png", "Y-{}"),
            ("down-right.png", "X{} Y-{}")
        ]

        for i, (img_name, cmd) in enumerate(directions):
            row, col = divmod(i, 3)
            img_path = os.path.join("images", img_name)
            try:
                photo = tk.PhotoImage(file=img_path)
                btn = ttk.Button(button_frame, image=photo, width=36, command=lambda c=cmd: self.jog(c))
                btn.image = photo
            except Exception:
                btn = ttk.Button(button_frame, text=cmd, width=6, command=lambda c=cmd: self.jog(c))
            btn.grid(row=row, column=col, padx=2, pady=2)

        right_sub = ttk.Frame(main_jog_frame)
        right_sub.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(right_sub, text="Unlock", command=self.unlock).pack(fill=tk.X, pady=2)
        ttk.Button(right_sub, text="Reset", command=self.reset).pack(fill=tk.X, pady=2)
        ttk.Button(right_sub, text="Set Zero", command=self.set_zero).pack(fill=tk.X, pady=2)
        ttk.Button(right_sub, text="Home", command=self.home).pack(fill=tk.X, pady=2)

        cmd_frame = ttk.Frame(self.manual_tab)
        cmd_frame.pack(fill=tk.X, padx=5, pady=2)
        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(cmd_frame, text="Send", command=self.send_custom_cmd, width=5).pack(side=tk.RIGHT, padx=2)

    def setup_gcode_tab(self):
        # Sets up the G-code control tab UI
        run_frame = ttk.Frame(self.gcode_tab)
        run_frame.pack(fill=tk.X, pady=10)

        buttons_subframe = ttk.Frame(run_frame)
        buttons_subframe.pack(anchor=tk.CENTER)

        try:
            run_img = tk.PhotoImage(file="images/run.png")
            pause_img = tk.PhotoImage(file="images/pause.png")
            stop_img = tk.PhotoImage(file="images/stop.png")
        except tk.TclError:
            run_img = pause_img = stop_img = None

        button_width = 8
        self.start_btn = ttk.Button(buttons_subframe, image=run_img, text="Start", compound='top', command=self.start_gcode, state=tk.NORMAL, width=button_width)
        self.start_btn.image = run_img
        self.start_btn.pack(side=tk.LEFT, padx=1, pady=0)

        self.pause_btn = ttk.Button(buttons_subframe, image=pause_img, text="Pause", compound='top', command=self.toggle_pause_resume, state=tk.DISABLED, width=button_width)
        self.pause_btn.image = pause_img
        self.pause_btn.pack(side=tk.LEFT, padx=1, pady=0)

        self.stop_btn = ttk.Button(buttons_subframe, image=stop_img, text="Stop", compound='top', command=self.stop_gcode, state=tk.DISABLED, width=button_width)
        self.stop_btn.image = stop_img
        self.stop_btn.pack(side=tk.LEFT, padx=1, pady=0)

        self.gcode_notebook = ttk.Notebook(self.gcode_tab)
        self.gcode_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.engraving_tab = ttk.Frame(self.gcode_notebook)
        self.gcode_notebook.add(self.engraving_tab, text="Engraving")

        self.test_tab = ttk.Frame(self.gcode_notebook)
        self.gcode_notebook.add(self.test_tab, text="Test")

        work_frame = ttk.Frame(self.engraving_tab)
        work_frame.pack(fill=tk.X, pady=5)
        ttk.Label(work_frame, text="Work Area (mm):", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=5)
        
        self.info_label = ttk.Label(work_frame, 
                              text="⚠️ Set work area before loading image",
                              foreground="orange", font=("Arial", 8))
        self.info_label.pack(anchor=tk.W, padx=5, pady=2)
        
        self.image_info_frame = ttk.Frame(work_frame)
        self.image_info_label = ttk.Label(self.image_info_frame, text="No image loaded", 
                                         foreground="gray", font=("Arial", 8), justify=tk.LEFT)
        self.image_info_label.pack(anchor=tk.W, padx=5)
        
        self.work_inputs_frame = ttk.Frame(work_frame)
        
        ttk.Label(self.work_inputs_frame, text="X").pack(side=tk.LEFT, padx=2)
        self.work_x_entry = ttk.Entry(self.work_inputs_frame, textvariable=self.work_x, width=10)
        self.work_x_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(self.work_inputs_frame, text="Y").pack(side=tk.LEFT, padx=2)
        self.work_y_entry = ttk.Entry(self.work_inputs_frame, textvariable=self.work_y, width=10)
        self.work_y_entry.pack(side=tk.LEFT, padx=2)
        
        self.change_work_area_btn = ttk.Button(work_frame, text="Change Work Area", 
                                             command=self.toggle_work_area_edit_mode, 
                                             state=tk.DISABLED)
        self.change_work_area_btn.pack(anchor=tk.W, padx=5, pady=2)
        
        self.apply_work_area_btn = ttk.Button(work_frame, text="Apply Work Area", 
                                            command=self.apply_work_area_changes,
                                            state=tk.DISABLED)
        self.apply_work_area_btn.pack(anchor=tk.W, padx=5, pady=2)
        self.apply_work_area_btn.pack_forget()

        power_frame = ttk.Frame(self.engraving_tab)
        power_frame.pack(fill=tk.X, pady=5)
        ttk.Label(power_frame, text="Power (%):", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=5)
        power_inputs = ttk.Frame(power_frame)
        power_inputs.pack(fill=tk.X, padx=5)
        ttk.Label(power_inputs, text="Min").pack(side=tk.LEFT, padx=2)
        ttk.Entry(power_inputs, textvariable=self.min_power, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(power_inputs, text="Max").pack(side=tk.LEFT, padx=2)
        ttk.Entry(power_inputs, textvariable=self.max_power, width=10).pack(side=tk.LEFT, padx=2)

        burn_speed_frame = ttk.Frame(self.engraving_tab)
        burn_speed_frame.pack(fill=tk.X, pady=5)
        ttk.Label(burn_speed_frame, text="Burn Speed (mm/min):", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
        ttk.Entry(burn_speed_frame, textvariable=self.burn_speed, width=10).pack(side=tk.LEFT, padx=5)
        
        contrast_frame = ttk.Frame(self.engraving_tab)
        contrast_frame.pack(fill=tk.X, pady=5)
        label_frame = ttk.Frame(contrast_frame)
        label_frame.pack(fill=tk.X, padx=5)
        self.contrast_var = tk.DoubleVar(value=1.0)
        ttk.Label(label_frame, text="Contrast (default 1.0):", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(label_frame, textvariable=self.contrast_var, width=5).pack(side=tk.RIGHT)
        contrast_scale = ttk.Scale(contrast_frame, from_=0.1, to=2.0, orient=tk.HORIZONTAL, variable=self.contrast_var, command=self.on_slider_change)
        contrast_scale.pack(fill=tk.X, padx=5, pady=2)        

        brightness_frame = ttk.Frame(self.engraving_tab)
        brightness_frame.pack(fill=tk.X, pady=5)
        label_frame = ttk.Frame(brightness_frame)
        label_frame.pack(fill=tk.X, padx=5)
        self.brightness_var = tk.DoubleVar(value=1.0)        
        ttk.Label(label_frame, text="Brightness (default 1.0):", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(label_frame, textvariable=self.brightness_var, width=5).pack(side=tk.RIGHT)
        brightness_scale = ttk.Scale(brightness_frame, from_=0.1, to=2.0, orient=tk.HORIZONTAL, variable=self.brightness_var, command=self.on_slider_change)
        brightness_scale.pack(fill=tk.X, padx=5, pady=2)        

        test_frame = ttk.Frame(self.test_tab)
        test_frame.pack(fill=tk.X, pady=5)

        ttk.Label(test_frame, text="Test Work Area (mm)", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=5)
        test_work_inputs = ttk.Frame(test_frame)
        test_work_inputs.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(test_work_inputs, text="X").pack(side=tk.LEFT, padx=2)
        ttk.Entry(test_work_inputs, textvariable=self.test_work_x, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(test_work_inputs, text="Y").pack(side=tk.LEFT, padx=2)
        ttk.Entry(test_work_inputs, textvariable=self.test_work_y, width=8).pack(side=tk.LEFT, padx=2)

        ttk.Label(test_frame, text="Power Range (%)", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=5, pady=(5, 0))
        test_power_inputs = ttk.Frame(test_frame)
        test_power_inputs.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(test_power_inputs, text="Steps").pack(side=tk.LEFT, padx=2)
        ttk.Entry(test_power_inputs, textvariable=self.test_x_steps, width=8).pack(side=tk.LEFT, padx=2)
        test_power_min_max = ttk.Frame(test_frame)
        test_power_min_max.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(test_power_min_max, text="Min").pack(side=tk.LEFT, padx=2)
        ttk.Entry(test_power_min_max, textvariable=self.test_min_power, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(test_power_min_max, text="Max").pack(side=tk.LEFT, padx=2)
        ttk.Entry(test_power_min_max, textvariable=self.test_max_power, width=8).pack(side=tk.LEFT, padx=2)

        ttk.Label(test_frame, text="Speed Range (mm/min)", font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=5, pady=(5, 0))
        test_speed_inputs = ttk.Frame(test_frame)
        test_speed_inputs.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(test_speed_inputs, text="Steps").pack(side=tk.LEFT, padx=2)
        ttk.Entry(test_speed_inputs, textvariable=self.test_y_steps, width=8).pack(side=tk.LEFT, padx=2)
        
        test_speed_min_max = ttk.Frame(test_frame)
        test_speed_min_max.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(test_speed_min_max, text="Min").pack(side=tk.LEFT, padx=2)
        ttk.Entry(test_speed_min_max, textvariable=self.test_min_speed, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(test_speed_min_max, text="Max").pack(side=tk.LEFT, padx=2)
        ttk.Entry(test_speed_min_max, textvariable=self.test_max_speed, width=8).pack(side=tk.LEFT, padx=2)
        
        self.update_image_info_display()

    def toggle_work_area_edit_mode(self):
        # Toggles work area edit mode for engraving settings
        if not self.work_area_edit_mode:
            self.work_area_edit_mode = True
            self.info_label.config(text="✏️ Edit work area and click 'Apply Work Area'")
            self.image_info_frame.pack_forget()
            self.work_inputs_frame.pack(fill=tk.X, padx=5, pady=2)
            self.change_work_area_btn.config(state=tk.DISABLED)
            self.apply_work_area_btn.pack(anchor=tk.W, padx=5, pady=2)
            self.apply_work_area_btn.config(state=tk.NORMAL)
        else:
            self.work_area_edit_mode = False
            self.info_label.config(text="⚠️ Set work area before loading image")
            self.work_inputs_frame.pack_forget()
            self.apply_work_area_btn.pack_forget()
            self.change_work_area_btn.config(state=tk.NORMAL)
            self.update_image_info_display()

    def apply_work_area_changes(self):
        # Applies changes to work area and reloads image
        if self.image_loaded and self.current_filename:
            self.process_image(self.current_filename)
            messagebox.showinfo("Work Area Updated", 
                               f"Image has been reloaded with new work area:\n"
                               f"{self.work_x.get()} × {self.work_y.get()} mm")
        
        self.work_area_edit_mode = False
        self.info_label.config(text="⚠️ Set work area before loading image")
        self.work_inputs_frame.pack_forget()
        self.apply_work_area_btn.pack_forget()
        self.change_work_area_btn.config(state=tk.NORMAL)
        self.update_image_info_display()

    def update_image_info_display(self):
        # Updates the image information display on the UI
        if self.image_loaded and self.current_filename and self.original_image_info and self.converted_image_info:
            filename = os.path.basename(self.current_filename)
            work_x = self.work_x.get()
            work_y = self.work_y.get()
            orig_width, orig_height = self.original_image_info
            conv_width, conv_height = self.converted_image_info
            
            info_text = (f"Loaded: {filename}\n"
                        f"Original: {orig_width}×{orig_height} px\n"
                        f"Converted: {conv_width}×{conv_height} px\n"
                        f"Work area: {work_x}×{work_y} mm")
            self.image_info_label.config(text=info_text, foreground="black")
            
            if not self.work_area_edit_mode:
                self.image_info_frame.pack(fill=tk.X, padx=5, pady=2)
                self.work_inputs_frame.pack_forget()
                self.apply_work_area_btn.pack_forget()
                self.change_work_area_btn.config(state=tk.NORMAL)
        else:
            if not self.work_area_edit_mode:
                self.image_info_frame.pack_forget()
                self.work_inputs_frame.pack(fill=tk.X, padx=5, pady=2)
                self.apply_work_area_btn.pack_forget()
                self.change_work_area_btn.config(state=tk.DISABLED)
                self.image_info_label.config(text="No image loaded", foreground="gray")
        self.update_start_button_state()

    def load_settings(self):
        # Loads application settings from a JSON file
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        return {
            'work_x': DEFAULT_WORK_X,
            'work_y': DEFAULT_WORK_Y,
            'min_power': DEFAULT_MIN_POWER,
            'max_power': DEFAULT_MAX_POWER,
            'burn_speed': DEFAULT_BURN_SPEED,
            'last_dir': DEFAULT_LAST_DIR,
            'step': '1',
            'multiplier': '1',
            'test_work_x': DEFAULT_TEST_WORK_X,
            'test_work_y': DEFAULT_TEST_WORK_Y,
            'test_x_steps': DEFAULT_TEST_X_STEPS,
            'test_min_power': DEFAULT_TEST_MIN_POWER,
            'test_max_power': DEFAULT_TEST_MAX_POWER,
            'test_y_steps': DEFAULT_TEST_Y_STEPS,
            'test_min_speed': DEFAULT_TEST_MIN_SPEED,
            'test_max_speed': DEFAULT_TEST_MAX_SPEED
        }

    def save_settings(self, *args):
        # Saves application settings to a JSON file
        settings = {
            'work_x': self.work_x.get(),
            'work_y': self.work_y.get(),
            'min_power': self.min_power.get(),
            'max_power': self.max_power.get(),
            'burn_speed': self.burn_speed.get(),
            'last_dir': self.last_dir,
            'step': self.step_var.get(),
            'multiplier': self.multiplier_var.get(),
            'test_work_x': self.test_work_x.get(),
            'test_work_y': self.test_work_y.get(),
            'test_x_steps': self.test_x_steps.get(),
            'test_min_power': self.test_min_power.get(),
            'test_max_power': self.test_max_power.get(),
            'test_y_steps': self.test_y_steps.get(),
            'test_min_speed': self.test_min_speed.get(),
            'test_max_speed': self.test_max_speed.get()
        }
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)

    def exit_app(self):
        # Exits the application and cleans up resources
        if self.tester and self.tester.running and not self.tester.paused:
            self.tester.stop()
            start_time = time.time()
            while self.tester.pending_commands > 0 and (time.time() - start_time < 2):
                time.sleep(0.1)
            if self.tester.ser.is_open:
                self.tester.ser.close()

        self.save_settings()
        if self.connected:
            self.toggle_connect()
        self.root.quit()

    def load_image(self):
        # Loads an image file for engraving
        file_types = [
            ("Image files", "*.jpg *.JPG *.png *.PNG *.bmp *.BMP *.gif *.GIF"),
            ("All files", "*.*")
        ]
        file_path = filedialog.askopenfilename(initialdir=self.last_dir, filetypes=file_types)
        if file_path:
            self.last_dir = os.path.dirname(file_path)
            self.save_settings()
            self.current_filename = file_path
            self.contrast_var.set(1.0)
            self.brightness_var.set(1.0)
            self.process_image(file_path)
            self.image_loaded = True
            self.work_area_edit_mode = False
            self.update_image_info_display()
            self.start_btn.config(state=tk.NORMAL)

    def process_image(self, file_path):
        # Processes an image for engraving with specified work area
        try:
            img = Image.open(file_path)
            self.original_image_info = (img.width, img.height)
            
            if img.mode == 'RGBA':
                white_bg = Image.new('RGB', img.size, (255, 255, 255))
                white_bg.paste(img, mask=img.split()[3])
                img = white_bg
            img = img.convert('L')
            
            dpi = 254
            res_mm = 25.4 / dpi
            pixels_x = int(self.work_x.get() / res_mm)
            pixels_y = int(self.work_y.get() / res_mm)
            
            orig_ratio = img.width / img.height
            target_ratio = pixels_x / pixels_y
            
            if orig_ratio > target_ratio:
                new_width = pixels_x
                new_height = int(pixels_x / orig_ratio)
            else:
                new_height = pixels_y
                new_width = int(pixels_y * orig_ratio)
                
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            padded = Image.new("L", (pixels_x, pixels_y), 255)
            paste_x = (pixels_x - new_width) // 2
            paste_y = (pixels_y - new_height) // 2
            padded.paste(resized, (paste_x, paste_y))
            
            self.converted_image_info = (pixels_x, pixels_y)
            self.base_image = padded
            self.processed_image = padded
            self.image_array = np.flipud(np.array(padded, dtype=np.uint8))
            self.resize_original()
            
        except Exception as e:
            messagebox.showerror("Image Processing Error", f"Failed to process image: {str(e)}")
            self.image_loaded = False
            self.update_image_info_display()

    def on_slider_change(self, value):
        # Updates image contrast or brightness based on slider input
        rounded = round(float(value) / 0.05) * 0.05
        formatted_value = f"{rounded:.2f}"
        if self.contrast_var.get() == float(value):
            self.contrast_var.set(formatted_value)
        elif self.brightness_var.get() == float(value):
            self.brightness_var.set(formatted_value)
        self.update_image()

    def update_image(self):
        # Applies contrast and brightness adjustments to the image
        if self.base_image:
            img = self.base_image.copy()
            if self.contrast_var.get() != 1.0:
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(self.contrast_var.get())
            if self.brightness_var.get() != 1.0:
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(self.brightness_var.get())
            self.processed_image = img
            self.image_array = np.flipud(np.array(img, dtype=np.uint8))
            self.resize_original()

    def resize_original(self, event=None):
        # Resizes the displayed image to fit the canvas
        if self.processed_image:
            canvas_width = self.top_canvas.winfo_width()
            canvas_height = self.top_canvas.winfo_height()
            img_width, img_height = self.processed_image.size
            scale = min(canvas_width / img_width, canvas_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)
            resized = self.processed_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            self.original_photo = ImageTk.PhotoImage(resized)
            self.top_canvas.delete("all")
            self.top_canvas.create_image(canvas_width // 2, canvas_height // 2, image=self.original_photo)

    def refresh_ports(self):
        # Refreshes available serial ports in the UI
        ports = [p.device for p in serial.tools.list_ports.comports() if not p.device.startswith('/dev/ttyS')]
        self.ports_menu['values'] = ports
        if ports:
            self.ports_var.set(ports[0])

    def toggle_connect(self):
        # Toggles serial connection to the laser device
        if not self.connected:
            port = self.ports_var.get()
            baudrate = self.baudrate_var.get()
            if not port:
                return
            self.ser = serial.Serial(port, int(baudrate), timeout=0)
            self.connected = True
            self.connect_btn.config(text="Disconnect")
        else:
            self.connected = False
            if self.ser.is_open:
                self.ser.close()
            self.connect_btn.config(text="Connect")

    def send_cmd(self, cmd):
        # Sends a G-code command to the laser device
        if self.connected and self.ser.is_open:
            self.ser.write((cmd + "\n").encode())
            self.cmd_monitor.insert(tk.END, cmd + "\n")
            self.cmd_monitor.see(tk.END)

    def jog(self, cmd_template):
        # Sends a jog command to move the laser head
        step = float(self.step_var.get()) * float(self.multiplier_var.get())
        if cmd_template == "ZERO":
            self.send_cmd(RETURN_ZERO_CMD)
        else:
            direction = cmd_template.format(step, step)
            self.send_cmd(f"G91 {direction}")

    def home(self):
        # Sends a home command to the laser device
        self.send_cmd(HOME_CMD)

    def set_zero(self):
        # Sets the current position as zero
        self.send_cmd(SET_ZERO_CMD)

    def unlock(self):
        # Unlocks the laser device
        self.send_cmd(UNLOCK_CMD)

    def reset(self):
        # Sends a soft reset command to the laser device
        self.send_cmd(SOFT_RESET)

    def send_custom_cmd(self):
        # Sends a custom G-code command from the UI entry
        cmd = self.cmd_entry.get()
        if cmd:
            self.send_cmd(cmd)
            self.cmd_entry.delete(0, tk.END)

    def start_gcode(self):
        # Starts the G-code engraving process based on active tab
        if not self.connected:
            return
        tab_id = self.gcode_notebook.select()
        tab_text = self.gcode_notebook.tab(tab_id, "text")
        
        if tab_text == "Engraving" and self.image_array is None:
            self.start_btn.config(state=tk.DISABLED)
            return
        else:
            self.start_btn.config(state=tk.NORMAL)
            
        if tab_text == "Engraving":
            min_power_percent = self.min_power.get()
            max_power_percent = self.max_power.get()
            work_speed = self.burn_speed.get()
            image_array = self.image_array
            test_params = None
            target_func = lambda: self.tester.start()
        elif tab_text == "Test":
            min_power_percent = 0
            max_power_percent = 0
            work_speed = 0
            image_array = None
            test_params = {
                'work_x': self.test_work_x.get(),
                'work_y': self.test_work_y.get(),
                'x_steps': self.test_x_steps.get(),
                'min_power': self.test_min_power.get(),
                'max_power': self.test_max_power.get(),
                'y_steps': self.test_y_steps.get(),
                'min_speed': self.test_min_speed.get(),
                'max_speed': self.test_max_speed.get()
            }
            target_func = lambda: self.tester.start_test()
        else:
            return
            
        self.tester = GrblWindowTester(
            port=self.ports_var.get(),
            baudrate=int(self.baudrate_var.get()),
            min_power_percent=min_power_percent,
            max_power_percent=max_power_percent,
            work_speed=work_speed,
            image_array=image_array,
            test_params=test_params
        )
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL)
        threading.Thread(target=target_func).start()

    def toggle_pause_resume(self):
        # Toggles pause/resume state of the engraving process
        if self.tester:
            self.tester.paused = not self.tester.paused
            self.pause_btn.config(text="Resume" if self.tester.paused else "Pause")

    def stop_gcode(self):
        # Stops the G-code engraving process
        if self.tester:
            self.tester.stop()
        self.root.after(100, self.update_buttons_after_stop)

    def update_buttons_after_stop(self):
        # Updates button states after stopping engraving
        tab_id = self.gcode_notebook.select()
        tab_text = self.gcode_notebook.tab(tab_id, "text")
        if tab_text == "Engraving" and self.image_array is None:
            self.start_btn.config(state=tk.DISABLED)
        else:
            self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = ImGlaserApp(root)
    root.mainloop()