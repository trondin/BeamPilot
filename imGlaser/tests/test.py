import serial
import threading
import time
from queue import Queue
import numpy as np
from PIL import Image
import os

CMD_BUFF_DEPTH = 10
USB_PORT = '/dev/ttyUSB0'
BAUDRATE = 115200
WORK_SPEED = 2500
IDLE_SPEED = 2500
MAX_POWER_PERCENT = 50
MIN_POWER_PERCENT = 5
LASER_MAX = 1000
PIC_FILE = 'pic.png'
PIXEL_SIZE_MM = 0.1
Y_STEP_MM = 0.1
ACCEL_PAD_MM = 3.0
LOG_FILE = 'log.txt'
SERIAL_SLEEP = 0.0001
LOG_ENABLED = False #True  

class GrblWindowTester:
    def __init__(self, port=USB_PORT, baudrate=BAUDRATE):
        self.ser = serial.Serial(port, baudrate, timeout=0, write_timeout=0)
        self.rx_buffer = bytearray()
        
        # Command window system
        self.window_size = CMD_BUFF_DEPTH
        self.pending_commands = 0
        self.total_sent = 0
        self.total_ok = 0
        
        self.command_queue = Queue()
        self.send_allowed = False
        self.running = True
        
        # Event for synchronizing command execution
        self.ok_event = threading.Event()
        
        # Laser power mapping array
        self.laser_map = self._create_laser_map()
        
        # Acceleration padding
        self.left_pad_mm = ACCEL_PAD_MM
        self.right_pad_mm = ACCEL_PAD_MM
        
        # Current X position
        self.current_x = 0.0
        
        # Logging (pure G-code commands)
        self.log_file = open(os.path.join(os.path.dirname(__file__), LOG_FILE), 'w', encoding='utf-8') if LOG_ENABLED else None

    def _create_laser_map(self):
        # Creates laser power mapping based on pixel brightness
        max_power = int(LASER_MAX * MAX_POWER_PERCENT / 100)
        min_power = int(LASER_MAX * MIN_POWER_PERCENT / 100)
        laser_map = np.zeros(256, dtype=int)
        
        # Linear interpolation for brightness 0-254 using linspace
        laser_map[:255] = np.linspace(max_power, min_power, 255, dtype=int)
        
        # Brightness 255 = 0 (laser off)
        laser_map[255] = 0
        return laser_map

    def _load_and_preprocess_image(self):
        # Load and preprocess image
        try:
            img = Image.open(PIC_FILE)           
            print(f"Image parameters:")
            print(f"  Format: {img.format}, Size: {img.size}, Mode: {img.mode}")
            # Convert to grayscale if needed
            if img.mode != 'L':
                img = img.convert('L')
                print("  Converted to grayscale")
            # Convert to numpy array and flip vertically
            img_array = np.flipud(np.array(img, dtype=np.uint8))         
            print(f"  Data type: {img_array.dtype}")
            print(f"  Brightness range: {img_array.min()} - {img_array.max()}")
            return img_array            
        except Exception as e:
            print(f"Image load error: {e}")
            return None

    def _execute(self):
        self.send_allowed = True
        while not self.command_queue.empty() or self.pending_commands > 0:
            self.ok_event.wait()  # Wait for an "ok" response
            self.ok_event.clear()  # Reset the event for the next wait
        self.send_allowed = False

    def _initialize_grbl(self):
        init_cmds = [
            b'$120=600\n',
            b'$121=600\n',
            b'G91\n'
        ]
        for cmd in init_cmds:
            if LOG_ENABLED and self.log_file:
                self.log_file.write(f"{cmd.decode('utf-8', errors='ignore').strip()}\n")
                self.log_file.flush()
            self.command_queue.put(cmd)
        self._execute()

    def _engrave_row(self, row, row_number, total_rows, direction, image_width_mm):
        # Engrave a single row in zigzag with optimization
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
        
        # Find non-zero indices
        non_zero_indices = np.argwhere(mapped_row != 0)
        trim_start_idx = non_zero_indices[0][0]
        trim_end_idx = non_zero_indices[-1][0] + 1
        trimmed_row = mapped_row[trim_start_idx:trim_end_idx]
        
        # Calculate required_start_mm
        if direction == 1:
            effective_start_mm = trim_start_idx * PIXEL_SIZE_MM
            required_start_mm = effective_start_mm - pad_start_mm
        else:
            effective_start_mm = image_width_mm - trim_start_idx * PIXEL_SIZE_MM
            required_start_mm = effective_start_mm + pad_start_mm
        
        cmds = []
        
        # Move to acceleration position at idle speed, if needed
        delta_to_start = required_start_mm - self.current_x
        if abs(delta_to_start) > 0.01:
            cmds.append(f'G1 X{delta_to_start:.1f} F{IDLE_SPEED}\n'.encode())
        
        # Engraving commands
        cmds.append(f'F{WORK_SPEED}\n'.encode())
        cmds.append(b'M3 S0\n')
        if pad_start_mm > 0:
            cmds.append(f'G1 X{(x_dir * pad_start_mm):.1f} S0\n'.encode())
        
        # Process pixel groups with same power
        i = 0
        n = len(trimmed_row)
        while i < n:
            s = trimmed_row[i]
            start = i
            while i < n and trimmed_row[i] == s:
                i += 1
            length = i - start
            dist = length * PIXEL_SIZE_MM
            cmds.append(f'G1 X{(x_dir * dist):.1f} S{s}\n'.encode())
        
        if pad_end_mm > 0:
            cmds.append(f'G1 X{(x_dir * pad_end_mm):.1f} S0\n'.encode())
        
        cmds.append(b'M5\n')
        
        # Log and queue commands
        if LOG_ENABLED and self.log_file:
            for cmd in cmds:
                self.log_file.write(f"{cmd.decode('utf-8', errors='ignore').strip()}\n")
            self.log_file.flush()
        for cmd in cmds:
            self.command_queue.put(cmd)
        print(f"Row {row_number}/{total_rows}, commands: {len(cmds)}")
        
        # Update current_x (first idle move, then engrave delta)
        if abs(delta_to_start) > 0.01:
            self.current_x += delta_to_start
        engrave_delta = x_dir * (pad_start_mm + len(trimmed_row) * PIXEL_SIZE_MM + pad_end_mm)
        self.current_x += engrave_delta
        
        self._execute()

    def rx_interrupt_handler(self):
        # Handle incoming "ok" responses
        while self.running:
            if self.ser.in_waiting > 0:
                try:
                    data = self.ser.read(self.ser.in_waiting)
                    self.rx_buffer.extend(data)
                    
                    # Process all "ok" responses in buffer
                    while b'ok\r' in self.rx_buffer:
                        ok_pos = self.rx_buffer.find(b'ok\r')
                        self.rx_buffer = self.rx_buffer[ok_pos + 3:]
                        
                        # Decrease pending commands and signal event
                        if self.pending_commands > 0:
                            self.pending_commands -= 1
                            self.total_ok += 1
                            self.ok_event.set()  # Signal that an "ok" was received
                except Exception as e:
                    print(f"Error in rx_interrupt_handler: {e}")
            
            time.sleep(SERIAL_SLEEP)

    def tx_interrupt_handler(self):
        # Handle command transmission with window control
        while self.running:
            if (self.send_allowed and
                self.pending_commands < self.window_size and
                not self.command_queue.empty() and
                self.ser.out_waiting == 0):
                cmd = self.command_queue.get()
                try:
                    self.ser.write(cmd)
                    self.pending_commands += 1
                    self.total_sent += 1
                except Exception as e:
                    print(f"Error sending command: {e}")
            
            time.sleep(SERIAL_SLEEP)

    def start(self):
        """Main engraving method"""
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(0.1)
        
        # Start processing threads
        self.rx_thread = threading.Thread(target=self.rx_interrupt_handler)
        self.tx_thread = threading.Thread(target=self.tx_interrupt_handler)
        self.rx_thread.daemon = True
        self.tx_thread.daemon = True
        self.rx_thread.start()
        self.tx_thread.start()

        # Load and process image
        img = self._load_and_preprocess_image()
        if img is None:
            self.stop()
            return        
        height, width = img.shape
        image_width_mm = width * PIXEL_SIZE_MM          
        # Precompute empty rows
        self.is_empty = [np.all(self.laser_map[row] == 0) for row in img]
        
        # Initialize GRBL   
        self._initialize_grbl()
        
        # Main zigzag engraving loop with empty row optimization
        direction = 1
        y = 0
        while y < height:
            if not self.running:
                break
            
            if self.is_empty[y]:
                empty_count = 1
                while y + empty_count < height and self.is_empty[y + empty_count]:
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
                if y < height:
                    cmd_str = f'G1 Y{Y_STEP_MM:.1f} F{IDLE_SPEED}\n'
                    cmd = cmd_str.encode()
                    if LOG_ENABLED and self.log_file:
                        self.log_file.write(cmd_str)
                        self.log_file.flush()
                    self.command_queue.put(cmd)
                    self._execute()
        
        # Return to initial X position
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
        self.stop()

    def stop(self):
        print("\nInitiating shutdown...")
        self.running = False
        self.send_allowed = False
        
        # Clear command queue
        while not self.command_queue.empty():
            try:
                self.command_queue.get_nowait()
            except:
                pass
        
        # Wait for all pending commands to complete
        while self.pending_commands > 0:
            print(f"Waiting for completion: {self.pending_commands} commands in progress")
            time.sleep(0.1)
        
        # Close serial port
        if self.ser.is_open:
            try:
                self.ser.flush()
                self.ser.close()
                print("Serial port closed")
            except Exception as e:
                print(f"Error closing port: {e}")
        
        # Close log file
        if LOG_ENABLED and self.log_file:
            try:
                self.log_file.close()
                print("Log file closed")
            except Exception as e:
                print(f"Error closing log file: {e}")
        
        # Wait for threads to terminate
        if hasattr(self, 'rx_thread') and self.rx_thread:
            self.rx_thread.join(timeout=1.0)
        if hasattr(self, 'tx_thread') and self.tx_thread:
            self.tx_thread.join(timeout=1.0)       
        print("Program terminated")

if __name__ == "__main__":
    tester = GrblWindowTester('/dev/ttyUSB0', 115200)
    try:
        tester.start()
    except KeyboardInterrupt:
        print("\nWaiting for current movement to complete...")
        while tester.pending_commands > 0 or not tester.command_queue.empty():
            time.sleep(0.1)
        tester.stop()