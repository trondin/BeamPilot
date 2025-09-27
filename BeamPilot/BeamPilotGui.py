import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

DEFAULT_STEP_OPTIONS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
DEFAULT_MULTIPLIER_OPTIONS = ["0.1", "1", "10", "100"]
RIGHT_PANEL_WIDTH = 250

class BeamPilotGui(tk.Tk):
    def setup_gui(self):
        # Menu
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Load GCode", command=self.load_file)
        file_menu.add_command(label="Save", command=self.save_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit_app)

        # PanedWindow for resizable panels
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left panel: Graphics
        self.left_frame = tk.Frame(self)
        self.paned.add(self.left_frame, weight=1)
        self.canvas = tk.Canvas(self.left_frame, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<MouseWheel>", self.zoom)
        self.canvas.bind("<Button-4>", lambda e: self.zoom(e, delta=1))
        self.canvas.bind("<Button-5>", lambda e: self.zoom(e, delta=-1))
        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.size_label = tk.Label(self.left_frame, text="X: 0-0 Y: 0-0")
        self.size_label.pack(side=tk.BOTTOM)
        self.position_marker = self.canvas.create_oval(0, 0, 0, 0, fill="red")

        # Right panel: Controls with Notebook
        self.right_frame = tk.Frame(self, width=RIGHT_PANEL_WIDTH)
        self.right_frame.pack_propagate(False)
        self.paned.add(self.right_frame, weight=0)

        # Bind to <Configure> for dynamic sizing
        def update_sash(event=None):
            if self.winfo_width() > 1:  # Avoid setting if window not yet realized (width=1)
                self.paned.sashpos(0, self.winfo_width() - RIGHT_PANEL_WIDTH)
            else:
                # Fallback: Retry after a short delay if window not yet sized
                self.after(50, update_sash)

        self.bind("<Configure>", update_sash)
        self.update_idletasks()  # Force layout update
        update_sash()  # Call once immediately (in case already sized)

        # Create notebook (tabs)
        self.notebook = ttk.Notebook(self.right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Manual Control
        self.manual_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.manual_tab, text="Manual")
        self.setup_manual_tab()

        # Tab 2: G-code Run
        self.run_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.run_tab, text="G-code")
        self.setup_run_tab()

        # Tab 3: Process
        self.process_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.process_tab, text="Process")
        self.setup_process_tab()

        # Position Labels
        pos_frame = tk.Frame(self.right_frame)
        pos_frame.pack(fill=tk.X, padx=5, pady=5)
        self.pos_abs_label = tk.Label(pos_frame, text="Abs: X=0.000 Y=0.000", font=("Arial", 10))
        self.pos_abs_label.pack(anchor=tk.W, padx=5)
        self.pos_rel_label = tk.Label(pos_frame, text="Rel: X=0.000 Y=0.000", font=("Arial", 10))
        self.pos_rel_label.pack(anchor=tk.W, padx=5)

        # Command Monitor
        monitor_frame = tk.Frame(self.right_frame)
        monitor_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.cmd_monitor = tk.Text(monitor_frame, bg="black", fg="white", wrap=tk.WORD)
        self.cmd_monitor.pack(fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(monitor_frame, orient=tk.VERTICAL, command=self.cmd_monitor.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.cmd_monitor.config(yscrollcommand=scrollbar.set)

        self.warning_icon = tk.PhotoImage(name="::tk::icons::warning")

    def setup_manual_tab(self):
        # USB controls at the top
        usb_frame = ttk.Frame(self.manual_tab)
        usb_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(usb_frame, text="Port:", font=("Arial", 9, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(5, 2))     
        self.ports_var = tk.StringVar(value=self.last_port)
        self.ports_menu = ttk.Combobox(usb_frame, textvariable=self.ports_var, state="readonly")
        self.ports_menu.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(usb_frame, text="Baudrate:", font=("Arial", 9, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(5, 2))
        self.baudrate_var = tk.StringVar(value=self.last_baudrate)
        baudrates = ["9600", "19200", "38400", "57600", "115200", "230400"]
        baudrate_menu = ttk.Combobox(usb_frame, textvariable=self.baudrate_var, values=baudrates, state="readonly")
        baudrate_menu.pack(fill=tk.X, pady=(0, 5))

        buttons_frame = ttk.Frame(usb_frame)
        buttons_frame.pack(fill=tk.X, pady=5)

        self.refresh_ports_btn = ttk.Button(buttons_frame, text="Refresh", command=self.refresh_ports)
        self.refresh_ports_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        self.connect_btn = ttk.Button(buttons_frame, text="Connect", command=self.toggle_connect)
        self.connect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Manual controls
        controls_frame = ttk.Frame(self.manual_tab)
        controls_frame.pack(fill=tk.X)
        
        ttk.Label(controls_frame, text="Step:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=2)
        self.step_var = tk.StringVar(value=self.last_step)
        step_menu = ttk.Combobox(controls_frame, textvariable=self.step_var, values=DEFAULT_STEP_OPTIONS, 
                                state="readonly", width=5)
        step_menu.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(controls_frame, text="Multiplier:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=2)
        self.multiplier_var = tk.StringVar(value=self.last_multiplier)
        mult_menu = ttk.Combobox(controls_frame, textvariable=self.multiplier_var, values=DEFAULT_MULTIPLIER_OPTIONS, 
                                state="readonly", width=5)
        mult_menu.pack(side=tk.LEFT, padx=2)

        main_jog_frame = ttk.Frame(self.manual_tab)
        main_jog_frame.pack(pady=5, fill=tk.BOTH, expand=True)
        
        left_sub = ttk.Frame(main_jog_frame)
        left_sub.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        button_frame = ttk.Frame(left_sub)
        button_frame.pack(pady=5)
        
        directions = [
            ("up-left.png", "X-{} Y{}"), ("up.png", "Y{}"), ("up-right.png", "X{} Y{}"),
            ("left.png", "X-{}"), ("home.png", "ZERO"), ("right.png", "X{}"),
            ("down-left.png", "X-{} Y-{}"), ("down.png", "Y-{}"), ("down-right.png", "X{} Y-{}")
        ]
        
        for i, (img_name, cmd) in enumerate(directions):
            row, col = divmod(i, 3)
            img_path = os.path.join("images", img_name)
            try:
                photo = tk.PhotoImage(file=img_path)
            except Exception:
                photo = None
            if photo:
                btn = ttk.Button(button_frame, image=photo, width=36, command=lambda c=cmd: self.jog(c))
                btn.image = photo
            else:
                btn = ttk.Button(button_frame, text=cmd, width=6, command=lambda c=cmd: self.jog(c))
            btn.grid(row=row, column=col, padx=2, pady=2)

        right_sub = ttk.Frame(main_jog_frame)
        right_sub.pack(side=tk.RIGHT, fill=tk.Y)
        
        unlock_btn = ttk.Button(right_sub, text="Unlock", command=self.unlock)
        unlock_btn.pack(fill=tk.X, pady=2)
        
        reset_btn = ttk.Button(right_sub, text="Reset", command=self.reset)
        reset_btn.pack(fill=tk.X, pady=2)
        
        set_zero_btn = ttk.Button(right_sub, text="Set Zero", command=self.set_zero)
        set_zero_btn.pack(fill=tk.X, pady=2)
        
        home_btn = ttk.Button(right_sub, text="Home", command=self.home)
        home_btn.pack(fill=tk.X, pady=2)

        cmd_frame = ttk.Frame(self.manual_tab)
        cmd_frame.pack(fill=tk.X, padx=5, pady=2)
        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        send_btn = ttk.Button(cmd_frame, text="Send", command=self.send_custom_cmd, width=5)
        send_btn.pack(side=tk.RIGHT, padx=2)

    def setup_run_tab(self):
        run_frame = ttk.Frame(self.run_tab)
        run_frame.pack(fill=tk.X, pady=10)

        buttons_subframe = ttk.Frame(run_frame)
        buttons_subframe.pack(anchor=tk.CENTER)

        run_img = None
        pause_img = None
        stop_img = None
        try:
            run_img = tk.PhotoImage(file="images/run.png")
            pause_img = tk.PhotoImage(file="images/pause.png")
            stop_img = tk.PhotoImage(file="images/stop.png")
        except tk.TclError:
            pass

        start_btn = ttk.Button(buttons_subframe, image=run_img, text="Start", compound='top',
                              command=self.start_gcode)
        start_btn.image = run_img
        start_btn.pack(side=tk.LEFT, padx=1, pady=0)

        self.pause_btn = ttk.Button(buttons_subframe, image=pause_img, text="Pause", compound='top',
                                   command=self.toggle_pause_resume)
        self.pause_btn.image = pause_img
        self.pause_btn.pack(side=tk.LEFT, padx=1, pady=0)

        stop_btn = ttk.Button(buttons_subframe, image=stop_img, text="Stop", compound='top',
                             command=self.stop_gcode)
        stop_btn.image = stop_img
        stop_btn.pack(side=tk.LEFT, padx=1, pady=0)
        
        coords_frame = ttk.Frame(self.run_tab)
        coords_frame.pack(fill=tk.X, pady=5)
        ttk.Label(coords_frame, text="Display Coordinates:", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(5, 2))
        radio_frame = ttk.Frame(coords_frame)
        radio_frame.pack(fill=tk.X)
        ttk.Radiobutton(radio_frame, text="Absolute", variable=self.display_coords, value="absolute", 
                       command=self.update_position_marker).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(radio_frame, text="Relative", variable=self.display_coords, value="relative", 
                       command=self.update_position_marker).pack(side=tk.LEFT, padx=5)
        
        self.info_frame = ttk.Frame(self.run_tab)
        self.info_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.file_name_label = ttk.Label(self.info_frame, text="File Name: ", anchor=tk.W)
        self.file_name_label.pack(fill=tk.X, padx=5)
        self.x_size_label = ttk.Label(self.info_frame, text="X Size: ", anchor=tk.W)
        self.x_size_label.pack(fill=tk.X, padx=5)
        self.y_size_label = ttk.Label(self.info_frame, text="Y Size: ", anchor=tk.W)
        self.y_size_label.pack(fill=tk.X, padx=5)
        self.lines_label = ttk.Label(self.info_frame, text="Lines: ", anchor=tk.W)
        self.lines_label.pack(fill=tk.X, padx=5)
        self.max_working_speed_label = ttk.Label(self.info_frame, text="Max Working Speed: ", anchor=tk.W)
        self.max_working_speed_label.pack(fill=tk.X, padx=5)
        self.max_idle_speed_label = ttk.Label(self.info_frame, text="Max Idle Speed: ", anchor=tk.W)
        self.max_idle_speed_label.pack(fill=tk.X, padx=5)
        self.max_power_label = ttk.Label(self.info_frame, text="Max Power: ", anchor=tk.W)
        self.max_power_label.pack(fill=tk.X, padx=5)
        self.warning_label = ttk.Label(self.info_frame, text=" Warning: Laser power is 0", compound='left', foreground="red")        
        self.warning_label.pack_forget()

    def setup_process_tab(self):
        self.process_notebook = ttk.Notebook(self.process_tab)
        self.process_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Fix Tab
        self.fix_tab = ttk.Frame(self.process_notebook)
        self.process_notebook.add(self.fix_tab, text="Fix")

        power_label = ttk.Label(self.fix_tab, text="Power:", font=("Arial", 9, "bold"))
        power_label.pack(fill=tk.X, pady=(5, 2))
        power_entry = ttk.Entry(self.fix_tab, textvariable=self.power_fix_var)
        power_entry.pack(fill=tk.X, padx=5, pady=(0, 5))
        fix_btn = ttk.Button(self.fix_tab, text="Fix", command=self.run_fix)
        fix_btn.pack(fill=tk.X, padx=5, pady=5)

        # Scale Tab
        self.scale_tab = ttk.Frame(self.process_notebook)
        self.process_notebook.add(self.scale_tab, text="Scale")

        size_label = ttk.Label(self.scale_tab, text="Target Size (mm):", font=("Arial", 9, "bold"))
        size_label.pack(fill=tk.X, pady=(5, 2))
        size_frame = ttk.Frame(self.scale_tab)
        size_frame.pack(fill=tk.X, pady=5)
        ttk.Label(size_frame, text="X:").pack(side=tk.LEFT, padx=2)
        x_entry = ttk.Entry(size_frame, textvariable=self.max_x_var, width=10)
        x_entry.pack(side=tk.LEFT, padx=5)
        ttk.Label(size_frame, text="Y:").pack(side=tk.LEFT, padx=2)
        y_entry = ttk.Entry(size_frame, textvariable=self.max_y_var, width=10)
        y_entry.pack(side=tk.LEFT, padx=5)
        scale_btn = ttk.Button(self.scale_tab, text="Scale", command=self.run_scale)
        scale_btn.pack(fill=tk.X, padx=5, pady=5)

        # Optimize Tab
        self.optimize_tab = ttk.Frame(self.process_notebook)
        self.process_notebook.add(self.optimize_tab, text="Optimize")

        opt_label = ttk.Label(self.optimize_tab, text="Idle Travel Optimization:", font=("Arial", 9, "bold"))
        opt_label.pack(fill=tk.X, pady=(5, 2))
        opt_frame = ttk.Frame(self.optimize_tab)
        opt_frame.pack(fill=tk.X, pady=5)
        ttk.Radiobutton(opt_frame, text="Minimal", variable=self.opt_level_var, value="0").pack(anchor=tk.W, padx=5)
        ttk.Radiobutton(opt_frame, text="Medium", variable=self.opt_level_var, value="1").pack(anchor=tk.W, padx=5)
        ttk.Radiobutton(opt_frame, text="Maximum", variable=self.opt_level_var, value="2").pack(anchor=tk.W, padx=5)
        optimize_btn = ttk.Button(self.optimize_tab, text="Optimize", command=self.run_optimize)
        optimize_btn.pack(fill=tk.X, padx=5, pady=5)

        # Power/Speed Tab
        self.power_speed_tab = ttk.Frame(self.process_notebook)
        self.process_notebook.add(self.power_speed_tab, text="Power/Speed")

        speed_label = ttk.Label(self.power_speed_tab, text="Max Working Speed (mm/min):", font=("Arial", 9, "bold"))
        speed_label.pack(fill=tk.X, pady=(5, 2))
        speed_entry = ttk.Entry(self.power_speed_tab, textvariable=self.max_speed_var)
        speed_entry.pack(fill=tk.X, padx=5, pady=(0, 5))
        idle_speed_label = ttk.Label(self.power_speed_tab, text="Max Idle Speed (mm/min):", font=("Arial", 9, "bold"))
        idle_speed_label.pack(fill=tk.X, pady=(5, 2))
        idle_speed_entry = ttk.Entry(self.power_speed_tab, textvariable=self.max_idle_speed_var)
        idle_speed_entry.pack(fill=tk.X, padx=5, pady=(0, 5))
        speed_btn = ttk.Button(self.power_speed_tab, text="Adjust Speed", command=self.run_adjust_speed)
        speed_btn.pack(fill=tk.X, padx=5, pady=5)

        power_label = ttk.Label(self.power_speed_tab, text="Max Power:", font=("Arial", 9, "bold"))
        power_label.pack(fill=tk.X, pady=(5, 2))
        power_entry = ttk.Entry(self.power_speed_tab, textvariable=self.max_power_var)
        power_entry.pack(fill=tk.X, padx=5, pady=(0, 5))
        power_btn = ttk.Button(self.power_speed_tab, text="Adjust Power", command=self.run_adjust_power)
        power_btn.pack(fill=tk.X, padx=5, pady=5)

    def draw_gcode(self):
        if not self.gcode_loaded:
            return
            
        self.canvas.delete("all")
        self.paths = []
        self.line_to_path = {}
        current_x, current_y = 0.0, 0.0
        laser_on = False
        
        # Reset bounds and speeds
        self.min_x = self.min_y = float("inf")
        self.max_x = self.max_y = float("-inf")
        self.max_working_speed = 0.0
        self.max_idle_speed = 0.0
        self.max_power = 0.0
        
        for i, line in enumerate(self.gcode_lines):
            params = self.parse_params(line)
            new_x = params.get('X', current_x)
            new_y = params.get('Y', current_y)
            is_cut = False
            in_idle = False
            
            if 'G' in params:
                g_val = params['G']
                if g_val == 0:
                    laser_on = False
                elif g_val == 1:
                    laser_on = True
                elif g_val == 92:
                    dx = params.get('X', 0)
                    dy = params.get('Y', 0)
                    self.wcs_offset = (current_x - dx, current_y - dy)
                    self.last_g92_time = time.time()
                    current_x, current_y = dx, dy
            if 'M' in params:
                m_val = params['M']
                if m_val in (3, 4):
                    laser_on = True
                    in_idle = False
                elif m_val == 5:
                    laser_on = False
                    in_idle = True
            if 'F' in params:
                f_val = params['F']
                if line.upper().startswith('G0') or (in_idle and line.upper().startswith('G1')):
                    self.max_idle_speed = max(self.max_idle_speed, f_val)
                elif line.upper().startswith('G1'):
                    self.max_working_speed = max(self.max_working_speed, f_val)
            if 'S' in params:
                self.max_power = max(self.max_power, params['S'])
            if new_x != current_x or new_y != current_y:
                self.min_x = min(self.min_x, min(current_x, new_x))
                self.max_x = max(self.max_x, max(current_x, new_x))
                self.min_y = min(self.min_y, min(current_y, new_y))
                self.max_y = max(self.max_y, max(current_y, new_y))
                color = "blue" if (laser_on or params.get('S', 0) > 0) else "blue"
                dash = () if (laser_on or params.get('S', 0) > 0) else (2, 2)
                x1, y1 = self.model_to_canvas(current_x, current_y)
                x2, y2 = self.model_to_canvas(new_x, new_y)
                path_id = self.canvas.create_line(
                    x1, y1, x2, y2,
                    fill=color, dash=dash, tags=("gcode_path", f"path_{i}")
                )
                self.line_to_path[i] = len(self.paths)
                self.paths.append(path_id)
            current_x, current_y = new_x, new_y

        x1 = 0 * self.scale_factor + self.offset_x
        y_axis = 500 * self.scale_factor + self.offset_y
        x2 = 800 * self.scale_factor + self.offset_x
        self.canvas.create_line(x1, y_axis, x2, y_axis, arrow=tk.BOTH, tags="axis")
        x_axis = 100 * self.scale_factor + self.offset_x
        y1 = 0 * self.scale_factor + self.offset_y
        y2 = 600 * self.scale_factor + self.offset_y
        self.canvas.create_line(x_axis, y1, x_axis, y2, arrow=tk.BOTH, tags="axis")

        self.size_label.config(text=f"X: {self.min_x:.2f}-{self.max_x:.2f} Y: {self.min_y:.2f}-{self.max_y:.2f}" if self.min_x != float("inf") else "X: 0-0 Y: 0-0")
        self.update_position_marker()

    def update_position_labels(self):
        self.pos_abs_label.config(text=f"Abs: X={self.abs_position[0]:.3f} Y={self.abs_position[1]:.3f}")
        self.pos_rel_label.config(text=f"Rel: X={self.rel_position[0]:.3f} Y={self.rel_position[1]:.3f}")

    def update_position_marker(self):
        try:
            pos = self.rel_position if self.display_coords.get() == "relative" else self.abs_position
            cx, cy = self.model_to_canvas(pos[0], pos[1])
            if not self.canvas.find_withtag(self.position_marker):
                self.position_marker = self.canvas.create_oval(cx-5, cy-5, cx+5, cy+5, fill="red", tags="position")
            else:
                self.canvas.coords(self.position_marker, cx-5, cy-5, cx+5, cy+5)
        except Exception:
            print("Error updating position marker")
            cx, cy = self.model_to_canvas(self.abs_position[0], self.abs_position[1])
            self.position_marker = self.canvas.create_oval(cx-5, cy-5, cx+5, cy+5, fill="red", tags="position")

    def update_file_info(self):
        if not self.gcode_loaded:
            return
        basename = os.path.basename(self.current_file) if self.current_file else "N/A"
        x_range = f"{self.min_x:.2f}-{self.max_x:.2f}" if self.min_x != float('inf') else "0-0"
        y_range = f"{self.min_y:.2f}-{self.max_y:.2f}" if self.min_y != float('inf') else "0-0"
        self.file_name_label.config(text=f"File Name: {basename}")
        self.x_size_label.config(text=f"X Size: {x_range}")
        self.y_size_label.config(text=f"Y Size: {y_range}")
        self.lines_label.config(text=f"Lines: {len(self.gcode_lines)}")
        self.max_working_speed_label.config(text=f"Max Working Speed: {self.max_working_speed:.0f}")
        self.max_idle_speed_label.config(text=f"Max Idle Speed: {self.max_idle_speed:.0f}")
        self.max_power_label.config(text=f"Max Power: {self.max_power:.0f}")
        if self.max_power == 0:
            self.warning_label.pack(fill=tk.X)
        else:
            self.warning_label.pack_forget()

    def zoom(self, event, delta=None):
        if not self.gcode_loaded:
            return
            
        if delta is None:
            try:
                delta = 1 if event.delta > 0 else -1
            except Exception:
                delta = 1
                
        factor = 1.1 if delta > 0 else 0.9
        old_scale = self.scale_factor
        self.scale_factor *= factor
        
        try:
            cursor_x = event.x
            cursor_y = event.y
        except Exception:
            cursor_x = int(self.canvas.winfo_width() / 2)
            cursor_y = int(self.canvas.winfo_height() / 2)
            
        scale_ratio = factor
        self.offset_x = cursor_x - (cursor_x - self.offset_x) * scale_ratio
        self.offset_y = cursor_y - (cursor_y - self.offset_y) * scale_ratio
        
        self.canvas.scale("all", cursor_x, cursor_y, scale_ratio, scale_ratio)
        self.update_position_marker()

    def start_drag(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def drag(self, event):
        if not self.gcode_loaded:
            return
            
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        
        self.canvas.move("all", dx, dy)
        self.offset_x += dx
        self.offset_y += dy
        
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.update_position_marker()
