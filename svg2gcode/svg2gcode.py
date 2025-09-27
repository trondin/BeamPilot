import tkinter as tk
from tkinter import filedialog, messagebox
import os
import json
from xml.etree import ElementTree as ET
import math
import re
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from PIL import Image, ImageTk
import sys
from math import hypot
import time
import random

# Constants
RIGHT_PANEL_WIDTH = 250
CONFIG_FILE = 'svg2gcode_config.json'

# Transform utilities
def identity_matrix():
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

def mat_mul(A, B):
    # Multiply two SVG 2D affine matrices A*B
    a1,b1,c1,d1,e1,f1 = A
    a2,b2,c2,d2,e2,f2 = B
    a = a1*a2 + c1*b2
    b = b1*a2 + d1*b2
    c = a1*c2 + c1*d2
    d = b1*c2 + d1*d2
    e = a1*e2 + c1*f2 + e1
    f = b1*e2 + d1*f2 + f1
    return (a,b,c,d,e,f)

def apply_matrix(mat, pt):
    a,b,c,d,e,f = mat
    x,y = pt
    return (a*x + c*y + e, b*x + d*y + f)

def parse_transform(transform_str):
    # Parse SVG transform attribute into a single affine matrix
    if not transform_str:
        return identity_matrix()
    transform_str = transform_str.strip()
    pattern = re.compile(r'([a-zA-Z]+)\s*\(([^)]*)\)')
    mats = []
    for name, args_str in pattern.findall(transform_str):
        args = [float(s) for s in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', args_str)]
        name_lower = name.lower()
        if name_lower == 'matrix' and len(args) >= 6:
            mats.append((args[0], args[1], args[2], args[3], args[4], args[5]))
        elif name_lower == 'translate':
            tx = args[0] if len(args) >= 1 else 0.0
            ty = args[1] if len(args) >= 2 else 0.0
            mats.append((1.0, 0.0, 0.0, 1.0, tx, ty))
        elif name_lower == 'scale':
            sx = args[0] if len(args) >= 1 else 1.0
            sy = args[1] if len(args) >= 2 else sx
            mats.append((sx, 0.0, 0.0, sy, 0.0, 0.0))
        elif name_lower == 'rotate':
            ang = math.radians(args[0]) if len(args) >= 1 else 0.0
            cos_a = math.cos(ang)
            sin_a = math.sin(ang)
            rot = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
            if len(args) >= 3:
                cx = args[1]; cy = args[2]
                t1 = (1.0, 0.0, 0.0, 1.0, cx, cy)
                t2 = (1.0, 0.0, 0.0, 1.0, -cx, -cy)
                mats.append(mat_mul(mat_mul(t1, rot), t2))
            else:
                mats.append(rot)
        elif name_lower == 'skewx':
            ang = math.radians(args[0]) if len(args) >= 1 else 0.0
            mats.append((1.0, 0.0, math.tan(ang), 1.0, 0.0, 0.0))
        elif name_lower == 'skewy':
            ang = math.radians(args[0]) if len(args) >= 1 else 0.0
            mats.append((1.0, math.tan(ang), 0.0, 1.0, 0.0, 0.0))
    result = identity_matrix()
    for m in mats:
        result = mat_mul(result, m)
    return result

class SVGParser:
    def __init__(self, filename):
        self.tree = ET.parse(filename)
        self.root = self.tree.getroot()
        self.namespaces = {'svg': 'http://www.w3.org/2000/svg'}
        self.paths = []
        self.view_box = None
        self.width = None
        self.height = None
        self.parent_map = {c: p for p in self.root.iter() for c in p}
        self.transform_cache = {}  # Cache for transformation matrices
        self.min_x = float('inf')  # Bounding box min x
        self.min_y = float('inf')  # Bounding box min y
        self.max_x = float('-inf') # Bounding box max x
        self.max_y = float('-inf') # Bounding box max y
        self.parse()

    def update_bounds(self, point):
        # Update bounding box with a new point
        x, y = point
        self.min_x = min(self.min_x, x)
        self.min_y = min(self.min_y, y)
        self.max_x = max(self.max_x, x)
        self.max_y = max(self.max_y, y)

    def get_cumulative_transform(self, elem):
        # Get cached cumulative transformation matrix for element
        if elem in self.transform_cache:
            return self.transform_cache[elem]
        mats = []
        current = elem
        while current is not None:
            if current in self.transform_cache:
                mats.append(self.transform_cache[current])
                break
            t = current.attrib.get('transform')
            if t:
                mats.append(parse_transform(t))
            current = self.parent_map.get(current)
        cumulative = identity_matrix()
        for m in reversed(mats):
            cumulative = mat_mul(cumulative, m)
        self.transform_cache[elem] = cumulative
        return cumulative

    def parse(self):
        # Parse viewBox attribute
        if 'viewBox' in self.root.attrib:
            try:
                vb = re.split(r'[,\s]+', self.root.attrib['viewBox'].strip())
                self.view_box = list(map(float, [x for x in vb if x != '']))
            except Exception:
                self.view_box = [0, 0, 100, 100]

        def parse_dimension(value):
            # Parse SVG dimension attribute
            if value is None:
                return None
            match = re.match(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', value)
            return float(match.group(0)) if match else None

        self.width = parse_dimension(self.root.attrib.get('width'))
        self.height = parse_dimension(self.root.attrib.get('height'))

        # Use viewBox size if width/height not specified
        if (self.width is None or self.height is None) and self.view_box:
            try:
                self.width = self.view_box[2]
                self.height = self.view_box[3]
            except Exception:
                pass

        # Default dimensions if not specified
        if self.width is None:
            self.width = 100.0
        if self.height is None:
            self.height = 100.0

        # Find all path elements
        paths = list(self.root.iterfind('.//svg:path', self.namespaces))
        if not paths:
            for elem in self.root.iter():
                if elem.tag.endswith('path'):
                    paths.append(elem)

        for path_elem in paths:
            d = path_elem.attrib.get('d', '')
            if not d.strip():
                continue
            cumulative = self.get_cumulative_transform(path_elem)
            segments = self.parse_path(d)
            transformed = []
            for seg in segments:
                if isinstance(seg, tuple) and len(seg) == 2 and isinstance(seg[0], tuple):
                    p0 = apply_matrix(cumulative, seg[0])
                    p1 = apply_matrix(cumulative, seg[1])
                    self.update_bounds(p0)
                    self.update_bounds(p1)
                    transformed.append((p0, p1))
                elif isinstance(seg, tuple) and len(seg) == 5 and seg[0] == 'C':
                    p0 = apply_matrix(cumulative, seg[1])
                    c1 = apply_matrix(cumulative, seg[2])
                    c2 = apply_matrix(cumulative, seg[3])
                    end = apply_matrix(cumulative, seg[4])
                    self.update_bounds(p0)
                    self.update_bounds(c1)
                    self.update_bounds(c2)
                    self.update_bounds(end)
                    transformed.append(('C', p0, c1, c2, end))
                else:
                    transformed.append(seg)
            self.paths.append(transformed)

    def parse_path(self, d):
        # Tokenize path commands and numbers
        tokens = []
        i = 0
        number_re = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')
        while i < len(d):
            ch = d[i]
            if ch.isalpha():
                tokens.append(ch)
                i += 1
            elif ch.isspace() or ch == ',':
                i += 1
            else:
                m = number_re.match(d[i:])
                if m:
                    tokens.append(m.group(0))
                    i += len(m.group(0))
                else:
                    i += 1

        # Parse commands and their arguments
        commands = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if isinstance(tok, str) and tok.isalpha():
                cmd = tok
                i += 1
                args = []
                while i < len(tokens) and not (isinstance(tokens[i], str) and tokens[i].isalpha()):
                    try:
                        args.append(float(tokens[i]))
                    except Exception:
                        pass
                    i += 1
                commands.append((cmd, args))
            else:
                i += 1

        segments = []
        pos = (0.0, 0.0)
        start_subpath = (0.0, 0.0)

        for cmd, args in commands:
            op = cmd.upper()
            is_rel = cmd.islower()

            def to_point(idx, base_pos=pos):
                # Convert relative/absolute coordinates to absolute point
                x = args[idx]
                y = args[idx+1]
                if is_rel:
                    return (base_pos[0] + x, base_pos[1] + y)
                else:
                    return (x, y)

            if op == 'M':
                if len(args) >= 2:
                    new_pos = to_point(0, pos)
                    pos = new_pos
                    start_subpath = pos
                    j = 2
                    while j + 1 < len(args):
                        next_pt = to_point(j, pos)
                        segments.append((pos, next_pt))
                        pos = next_pt
                        j += 2
            elif op == 'L':
                j = 0
                while j + 1 < len(args):
                    next_pt = to_point(j, pos)
                    segments.append((pos, next_pt))
                    pos = next_pt
                    j += 2
            elif op == 'H':
                for x in args:
                    nx = pos[0] + x if is_rel else x
                    next_pt = (nx, pos[1])
                    segments.append((pos, next_pt))
                    pos = next_pt
            elif op == 'V':
                for y in args:
                    ny = pos[1] + y if is_rel else y
                    next_pt = (pos[0], ny)
                    segments.append((pos, next_pt))
                    pos = next_pt
            elif op == 'C':
                j = 0
                while j + 5 < len(args):
                    if is_rel:
                        c1 = (pos[0] + args[j], pos[1] + args[j+1])
                        c2 = (pos[0] + args[j+2], pos[1] + args[j+3])
                        end = (pos[0] + args[j+4], pos[1] + args[j+5])
                    else:
                        c1 = (args[j], args[j+1])
                        c2 = (args[j+2], args[j+3])
                        end = (args[j+4], args[j+5])
                    segments.append(('C', pos, c1, c2, end))
                    pos = end
                    j += 6
            elif op == 'Z':
                if pos != start_subpath:
                    segments.append((pos, start_subpath))
                pos = start_subpath

        return segments

    def get_bounds(self):
        # Return precomputed bounding box
        if self.min_x == float('inf'):
            return 0, 0, self.width, self.height
        return self.min_x, self.min_y, self.max_x - self.min_x, self.max_y - self.min_y

class Approximator:
    @staticmethod
    def flatten_bezier(points, tolerance=0.1):
        # Flatten Bezier curve to line segments
        pts = list(points)
        if len(pts) != 4:
            return []

        def lerp(a, b, t):
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

        def split_bezier(p, t=0.5):
            p0, p1, p2, p3 = p
            p01 = lerp(p0, p1, t)
            p12 = lerp(p1, p2, t)
            p23 = lerp(p2, p3, t)
            p012 = lerp(p01, p12, t)
            p123 = lerp(p12, p23, t)
            p0123 = lerp(p012, p123, t)
            left = (p0, p01, p012, p0123)
            right = (p0123, p123, p23, p3)
            return left, right

        def dist_to_line(p, a, b):
            ab = (b[0] - a[0], b[1] - a[1])
            ap = (p[0] - a[0], p[1] - a[1])
            len2 = ab[0]**2 + ab[1]**2
            if len2 == 0:
                return math.hypot(ap[0], ap[1])
            t = (ap[0]*ab[0] + ap[1]*ab[1]) / len2
            if t < 0:
                return math.hypot(ap[0], ap[1])
            elif t > 1:
                return math.hypot(p[0] - b[0], p[1] - b[1])
            proj_pt = (a[0] + t*ab[0], a[1] + t*ab[1])
            return math.hypot(p[0] - proj_pt[0], p[1] - proj_pt[1])

        def flatten(points, tol, lines):
            stack = [tuple(points)]
            while stack:
                bez = stack.pop()
                d1 = dist_to_line(bez[1], bez[0], bez[3])
                d2 = dist_to_line(bez[2], bez[0], bez[3])
                if max(d1, d2) <= tol:
                    lines.append((bez[0], bez[3]))
                else:
                    left, right = split_bezier(bez)
                    stack.append(right)
                    stack.append(left)

        lines = []
        flatten(pts, tolerance, lines)
        return lines

class CanvasViewer(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.scale_factor = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.last_x = 0
        self.last_y = 0
        self.min_scale = 0.1
        self.max_scale = 10.0
        self.redraw_scheduled = False
        self.needs_redraw = True  # Flag to trigger redraw
        self.bind("<Button-1>", self.start_drag)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<MouseWheel>", self.zoom)
        self.bind("<Button-4>", self.zoom)
        self.bind("<Button-5>", self.zoom)
        self.bind("<Configure>", self.schedule_redraw)

    def start_drag(self, event):
        self.last_x = event.x
        self.last_y = event.y

    def drag(self, event):
        dx = event.x - self.last_x
        dy = event.y - self.last_y
        self.offset_x += dx
        self.offset_y += dy
        self.last_x = event.x
        self.last_y = event.y
        self.schedule_redraw()

    def zoom(self, event):
        if getattr(event, 'num', None) == 4 or getattr(event, 'delta', 0) > 0:
            factor = 1.1
        elif getattr(event, 'num', None) == 5 or getattr(event, 'delta', 0) < 0:
            factor = 0.9
        else:
            return
        new_scale = self.scale_factor * factor
        if self.min_scale <= new_scale <= self.max_scale:
            self.scale_factor = new_scale
            self.schedule_redraw()

    def schedule_redraw(self, event=None):
        if not self.redraw_scheduled:
            self.redraw_scheduled = True
            self.after(50, self.perform_redraw)

    def perform_redraw(self):
        self.redraw_scheduled = False
        self.redraw()

    def redraw(self):
        pass

class SVGViewer(tk.Canvas):
    def __init__(self, parent, width=100, height=100):
        super().__init__(parent, bg='white')
        self.image = None
        self.photo = None
        self.width = width
        self.height = height
        self.scale_factor = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.last_x = 0
        self.last_y = 0
        self.min_scale = 0.1
        self.max_scale = 10.0
        self.redraw_scheduled = False
        self.needs_redraw = True  # Flag to trigger redraw
        self.cached_scale = 1.0   # Cache for rendering parameters
        self.cached_offset_x = 0
        self.cached_offset_y = 0
        self.cached_size = (0, 0)
        self.bind("<Button-1>", self.start_drag)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<MouseWheel>", self.zoom)
        self.bind("<Button-4>", self.zoom)
        self.bind("<Button-5>", self.zoom)
        self.bind("<Configure>", self.schedule_redraw)

    def update_content(self, filename=None, width=100, height=100):
        # Update canvas with new SVG content
        self.width = width
        self.height = height
        self.scale_factor = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.delete('all')
        self.image = None
        self.photo = None
        if filename:
            try:
                drawing = svg2rlg(filename)
                img = renderPM.drawToPIL(drawing)
                self.image = img
                self.needs_redraw = True
                self.schedule_redraw()
            except Exception as e:
                print(f"Failed to render SVG: {e}")
        else:
            self.needs_redraw = True
            self.schedule_redraw()

    def start_drag(self, event):
        self.last_x = event.x
        self.last_y = event.y

    def drag(self, event):
        dx = event.x - self.last_x
        dy = event.y - self.last_y
        self.offset_x += dx
        self.offset_y += dy
        self.last_x = event.x
        self.last_y = event.y
        self.needs_redraw = True
        self.schedule_redraw()

    def zoom(self, event):
        if getattr(event, 'num', None) == 4 or getattr(event, 'delta', 0) > 0:
            factor = 1.1
        elif getattr(event, 'num', None) == 5 or getattr(event, 'delta', 0) < 0:
            factor = 0.9
        else:
            return
        new_scale = self.scale_factor * factor
        if self.min_scale <= new_scale <= self.max_scale:
            self.scale_factor = new_scale
            self.needs_redraw = True
            self.schedule_redraw()

    def schedule_redraw(self, event=None):
        if not self.redraw_scheduled:
            self.redraw_scheduled = True
            self.after(50, self.perform_redraw)

    def perform_redraw(self):
        self.redraw_scheduled = False
        self.redraw()

    def redraw(self):
        # Redraw only if necessary
        if not self.needs_redraw:
            return
        self.delete('all')
        if not self.image:
            self.needs_redraw = False
            return
        cw, ch = self.winfo_width(), self.winfo_height()
        if cw <= 1 or ch <= 1:
            return
        current_params = (self.scale_factor, self.offset_x, self.offset_y, cw, ch)
        cached_params = (self.cached_scale, self.cached_offset_x, self.cached_offset_y, 
                        self.cached_size[0], self.cached_size[1])
        draw_scale = min(cw / self.width, ch / self.height) * self.scale_factor
        new_size = (int(self.width * draw_scale), int(self.height * draw_scale))
        try:
            img = self.image.resize(new_size, Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(img)
            ox = self.offset_x + (cw - new_size[0]) / 2
            oy = self.offset_y + (ch - new_size[1]) / 2
            self.create_image(ox, oy, image=self.photo, anchor='nw')
        except Exception as e:
            print(f"Failed to redraw SVG: {e}")
        self.cached_scale = self.scale_factor
        self.cached_offset_x = self.offset_x
        self.cached_offset_y = self.offset_y
        self.cached_size = (cw, ch)
        self.needs_redraw = False

class LinesViewer(CanvasViewer):
    def __init__(self, parent, lines=None, width=100, height=100):
        super().__init__(parent, bg='white')
        self.lines = lines or []
        self.orig_width = width
        self.orig_height = height
        self.cached_lines = []  # Cache for rendered lines
        self.cached_scale = 1.0
        self.cached_offset_x = 0
        self.cached_offset_y = 0
        self.cached_size = (0, 0)
        self.redraw()

    def update_content(self, lines, width, height):
        # Update canvas with new line content
        self.lines = lines or []
        self.orig_width = width
        self.orig_height = height
        self.scale_factor = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.needs_redraw = True
        self.schedule_redraw()

    def redraw(self):
        # Redraw only if necessary
        cw, ch = self.winfo_width(), self.winfo_height()
        if cw <= 1 or ch <= 1:
            return
        current_params = (self.scale_factor, self.offset_x, self.offset_y, cw, ch)
        cached_params = (self.cached_scale, self.cached_offset_x, self.cached_offset_y, 
                        self.cached_size[0], self.cached_size[1])
        if not self.needs_redraw and current_params == cached_params:
            return
        self.delete('all')
        draw_scale = min(cw / self.orig_width, ch / self.orig_height) * self.scale_factor
        ox = self.offset_x + cw / 2 - (self.orig_width * draw_scale) / 2
        oy = self.offset_y + ch / 2 - (self.orig_height * draw_scale) / 2
        for line in self.lines:
            x1, y1 = line[0]
            x2, y2 = line[1]
            self.create_line(ox + x1 * draw_scale, oy + y1 * draw_scale,
                             ox + x2 * draw_scale, oy + y2 * draw_scale,
                             fill='black')
        self.cached_scale = self.scale_factor
        self.cached_offset_x = self.offset_x
        self.cached_offset_y = self.offset_y
        self.cached_size = (cw, ch)
        self.needs_redraw = False

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("SVG to GCode")
        self.root.geometry("800x600")
        self.config = self.load_config()
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Load", command=self.load_svg)
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)
        self.main_frame = tk.PanedWindow(root, orient='horizontal', sashwidth=5)
        self.main_frame.pack(fill='both', expand=True)
        self.left_frame = tk.PanedWindow(self.main_frame, orient='vertical', sashwidth=5)
        self.main_frame.add(self.left_frame, minsize=300)
        self.right_panel = tk.Frame(self.main_frame, width=RIGHT_PANEL_WIDTH)
        self.main_frame.add(self.right_panel, minsize=RIGHT_PANEL_WIDTH, width=RIGHT_PANEL_WIDTH)
        self.top_frame = tk.Frame(self.left_frame)
        self.bottom_frame = tk.Frame(self.left_frame)
        self.left_frame.add(self.top_frame, minsize=150)
        self.left_frame.add(self.bottom_frame, minsize=150)
        self.svg_viewer = SVGViewer(self.top_frame)
        self.svg_viewer.pack(fill='both', expand=True)
        self.lines_viewer = LinesViewer(self.bottom_frame)
        self.lines_viewer.pack(fill='both', expand=True)
        self.root.after(100, self.adjust_pane_ratio)
        self.left_frame.bind("<Configure>", self.adjust_pane_ratio)
        size_frame = tk.Frame(self.right_panel)
        size_frame.pack(fill='x', pady=5)
        size_x_frame = tk.Frame(size_frame)
        size_x_frame.pack(side='left', padx=10)
        tk.Label(size_x_frame, text="Size X (mm)").pack()
        self.size_x_entry = tk.Entry(size_x_frame, width=10)
        self.size_x_entry.insert(0, self.config.get('size_x', 100))
        self.size_x_entry.pack()
        size_y_frame = tk.Frame(size_frame)
        size_y_frame.pack(side='left', padx=10)
        tk.Label(size_y_frame, text="Size Y (mm)").pack()
        self.size_y_entry = tk.Entry(size_y_frame, width=10)
        self.size_y_entry.insert(0, self.config.get('size_y', 100))
        self.size_y_entry.pack()
        tk.Label(self.right_panel, text="Approximation Tolerance (mm):").pack()
        self.tol_entry = tk.Entry(self.right_panel)
        self.tol_entry.insert(0, self.config.get('tolerance', 0.1))
        self.tol_entry.pack()
        self.convert_btn = tk.Button(self.right_panel, text="Convert", command=self.convert)
        self.convert_btn.pack(pady=10)
        tk.Label(self.right_panel, text="Laser Settings", font=("Arial", 10, "bold")).pack(pady=(10, 0))
        laser_frame = tk.Frame(self.right_panel)
        laser_frame.pack(fill='x', pady=5)
        speed_frame = tk.Frame(laser_frame)
        speed_frame.pack(side='left', padx=5)
        tk.Label(speed_frame, text="Speed (mm/min)").pack()
        self.speed_entry = tk.Entry(speed_frame, width=8)
        self.speed_entry.insert(0, self.config.get('laser_speed', 1000))
        self.speed_entry.pack()
        idle_speed_frame = tk.Frame(laser_frame)
        idle_speed_frame.pack(side='left', padx=5)
        tk.Label(idle_speed_frame, text="Idle Speed (mm/min)").pack()
        self.idle_speed_entry = tk.Entry(idle_speed_frame, width=8)
        self.idle_speed_entry.insert(0, self.config.get('idle_speed', 2000))
        self.idle_speed_entry.pack()
        power_frame = tk.Frame(laser_frame)
        power_frame.pack(side='left', padx=5)
        tk.Label(power_frame, text="Power (0-1000)").pack()
        self.power_entry = tk.Entry(power_frame, width=8)
        self.power_entry.insert(0, self.config.get('laser_power', 255))
        self.power_entry.pack()
        tk.Label(self.right_panel, text="Optimization Level:").pack(pady=(10, 0))
        opt_frame = tk.Frame(self.right_panel)
        opt_frame.pack(fill='x', pady=5)
        self.opt_var = tk.StringVar(value=self.config.get('optimization', 'high'))
        opt_inner_frame = tk.Frame(opt_frame)
        opt_inner_frame.pack(anchor='center')
        tk.Radiobutton(opt_inner_frame, text="None", variable=self.opt_var, value='none').pack(side='left', padx=5)
        tk.Radiobutton(opt_inner_frame, text="Low", variable=self.opt_var, value='low').pack(side='left', padx=5)
        tk.Radiobutton(opt_inner_frame, text="Medium", variable=self.opt_var, value='medium').pack(side='left', padx=5)
        tk.Radiobutton(opt_inner_frame, text="High", variable=self.opt_var, value='high').pack(side='left', padx=5)
        self.gen_btn = tk.Button(self.right_panel, text="Generate GCode", command=self.generate_gcode)
        self.gen_btn.pack(pady=10)
        self.terminal = tk.Text(self.right_panel, height=10, state='normal')
        self.terminal.pack(fill='x', pady=5)
        self.svg_parser = None
        self.svg_filename = None
        self.lines = []
        self.scaled_width = 100
        self.scaled_height = 100

    def load_config(self):
        # Load configuration from JSON file
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {
            'last_dir': os.getcwd(),
            'size_x': 100,
            'size_y': 100,
            'tolerance': 0.1,
            'laser_speed': 1000,
            'idle_speed': 2000,
            'laser_power': 255,
            'optimization': 'high'
        }

    def save_config(self):
        # Save configuration to JSON file
        self.config['size_x'] = float(self.size_x_entry.get() or self.config.get('size_x', 100))
        self.config['size_y'] = float(self.size_y_entry.get() or self.config.get('size_y', 100))
        self.config['tolerance'] = float(self.tol_entry.get() or self.config.get('tolerance', 0.1))
        self.config['laser_speed'] = float(self.speed_entry.get() or self.config.get('laser_speed', 1000))
        self.config['idle_speed'] = float(self.idle_speed_entry.get() or self.config.get('idle_speed', 2000))
        self.config['laser_power'] = int(self.power_entry.get() or self.config.get('laser_power', 255))
        self.config['optimization'] = self.opt_var.get()
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f)

    def adjust_pane_ratio(self, event=None):
        # Adjust vertical pane to 50/50 split
        total_height = self.left_frame.winfo_height()
        if total_height > 0:
            half_height = total_height // 2
            self.left_frame.sash_place(0, 0, half_height)

    def load_svg(self):
        # Load SVG file and update viewers
        filename = filedialog.askopenfilename(initialdir=self.config['last_dir'], filetypes=[("SVG files", "*.svg")])
        if filename:
            self.config['last_dir'] = os.path.dirname(filename)
            self.save_config()
            try:
                self.svg_parser = SVGParser(filename)
                self.svg_filename = filename
                self.svg_viewer.update_content(filename, self.svg_parser.width, self.svg_parser.height)
                self.lines = []
                self.lines_viewer.update_content([], 100, 100)
            except Exception as e:
                if self.root.winfo_exists():
                    messagebox.showerror("Error", f"Failed to load SVG: {e}")
                else:
                    print(f"Error: Failed to load SVG: {e}")

    def convert(self):
        # Convert SVG to line segments
        if not self.svg_parser:
            if self.root.winfo_exists():
                messagebox.showwarning("Warning", "Load SVG first")
            return
        try:
            size_x = float(self.size_x_entry.get())
            size_y = float(self.size_y_entry.get())
            tol = float(self.tol_entry.get())
            if size_x <= 0 or size_y <= 0 or tol <= 0:
                raise ValueError("Values must be positive")
            self.config['size_x'] = size_x
            self.config['size_y'] = size_y
            self.config['tolerance'] = tol
            self.save_config()
        except ValueError as e:
            if self.root.winfo_exists():
                messagebox.showerror("Error", f"Invalid input values: {e}")
            return
        min_x, min_y, orig_width, orig_height = self.svg_parser.get_bounds()
        if orig_width <= 0 or orig_height <= 0:
            orig_lines = []
            for path in self.svg_parser.paths:
                for seg in path:
                    if isinstance(seg, tuple) and len(seg) == 2 and isinstance(seg[0], tuple):
                        orig_lines.append(seg)
                    elif isinstance(seg, tuple) and len(seg) == 5 and seg[0] == 'C':
                        approx = Approximator.flatten_bezier(seg[1:], tol)
                        orig_lines.extend(approx)
            if not orig_lines:
                messagebox.showwarning("Warning", "No paths found in SVG")
                return
            min_x = min_y = sys.float_info.max
            max_x = max_y = -sys.float_info.max
            for line in orig_lines:
                for p in line:
                    min_x = min(min_x, p[0])
                    min_y = min(min_y, p[1])
                    max_x = max(max_x, p[0])
                    max_y = max(max_y, p[1])
            orig_width = max_x - min_x
            orig_height = max_y - min_y
        if orig_width <= 0 or orig_height <= 0:
            messagebox.showerror("Error", "Invalid path bounds (zero or negative size)")
            return
        scale = min(size_x / orig_width, size_y / orig_height)
        final_width = orig_width * scale
        final_height = orig_height * scale
        def lines_generator():
            # Generate line segments for conversion
            for path in self.svg_parser.paths:
                for seg in path:
                    if isinstance(seg, tuple) and len(seg) == 2 and isinstance(seg[0], tuple):
                        yield seg
                    elif isinstance(seg, tuple) and len(seg) == 5 and seg[0] == 'C':
                        yield from Approximator.flatten_bezier(seg[1:], tol)
        self.lines = []
        for (p1, p2) in lines_generator():
            fp1_x = (p1[0] - min_x) * scale
            fp1_y = (p1[1] - min_y) * scale
            fp2_x = (p2[0] - min_x) * scale
            fp2_y = (p2[1] - min_y) * scale
            self.lines.append(((fp1_x, fp1_y), (fp2_x, fp2_y)))
        self.scaled_width = final_width
        self.scaled_height = final_height
        self.lines_viewer.update_content(self.lines, self.scaled_width, self.scaled_height)

    def dist_sq(self, a, b):
        # Calculate squared distance for fast comparisons
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        return dx*dx + dy*dy

    def total_travel(self, ordered_chains):
        # Calculate total travel distance for chains
        if not ordered_chains:
            return 0.0
        total = 0.0
        for i in range(len(ordered_chains) - 1):
            a = ordered_chains[i][-1]
            b = ordered_chains[i+1][0]
            total += hypot(a[0] - b[0], a[1] - b[1])
        return total

    def greedy_order_with_reversal_fast(self, chains):
        # Fast greedy algorithm with chain reversal
        if not chains:
            return []
        unused = chains[:]
        ordered = [unused.pop(0)]
        endpoints = [(chain[0], chain[-1]) for chain in unused]
        total_chains = len(chains)
        while unused:
            if len(ordered) % 100 == 0:
                self.log(f"Greedy progress: {len(ordered)} / {total_chains}")
            last_end = ordered[-1][-1]
            best_idx = 0
            best_orient = False
            best_d_sq = float('inf')
            for i, (start, end) in enumerate(endpoints):
                d_start_sq = self.dist_sq(last_end, start)
                d_end_sq = self.dist_sq(last_end, end)
                if d_start_sq < best_d_sq:
                    best_d_sq = d_start_sq
                    best_idx = i
                    best_orient = False
                if d_end_sq < best_d_sq:
                    best_d_sq = d_end_sq
                    best_idx = i
                    best_orient = True
            chain = unused.pop(best_idx)
            endpoints.pop(best_idx)
            if best_orient:
                chain = chain[::-1]
            ordered.append(chain)
        return ordered

    def optimize_orientation(self, order, i, j):
        # Optimize orientation between adjacent chains
        if j >= len(order):
            return
        prev_end = order[i][-1]
        chain = order[j]
        d0 = hypot(prev_end[0] - chain[0][0], prev_end[1] - chain[0][1])
        d1 = hypot(prev_end[0] - chain[-1][0], prev_end[1] - chain[-1][1])
        if d1 < d0:
            order[j] = order[j][::-1]

    def fast_local_improve(self, order, max_attempts=500):
        # Local optimization with random swaps or reversals
        n = len(order)
        if n < 3:
            return order, False
        current_score = self.total_travel(order)
        improved = False
        for attempt in range(max_attempts):
            i = random.randint(0, n-2)
            j = random.randint(i+1, n-1)
            new_order = order.copy()
            if random.random() < 0.7:
                new_order[i], new_order[j] = new_order[j], new_order[i]
            else:
                new_order[i:j+1] = new_order[i:j+1][::-1]
            start_idx = max(0, i-1)
            end_idx = min(n, j+2)
            for k in range(start_idx + 1, end_idx):
                if k < n:
                    self.optimize_orientation(new_order, k-1, k)
            new_score = self.total_travel(new_order)
            if new_score < current_score - 1e-9:
                order = new_order
                current_score = new_score
                improved = True
                self.log(f"Local improvement found: {new_score:.3f}")
        return order, improved

    def optimize_chains(self, chains, max_iter=20):
        # Optimize chain order
        if not chains:
            return []
        self.log(f"Chains found: {len(chains)}. Running greedy optimization...")
        order = self.greedy_order_with_reversal_fast(chains)
        initial_travel = self.total_travel(order)
        self.log(f"Initial greedy travel: {initial_travel:.3f}")
        iter_num = 0
        improved = True
        while iter_num < max_iter and improved:
            iter_num += 1
            self.log(f"Starting improvement iteration {iter_num}")
            order, improved = self.fast_local_improve(order)
            if improved:
                current_travel = self.total_travel(order)
                self.log(f"Iteration {iter_num}: travel = {current_travel:.3f}")
        final_travel = self.total_travel(order)
        self.log(f"Optimization done in {iter_num} iterations. Final travel = {final_travel:.3f}")
        self.log(f"Improvement: {((initial_travel - final_travel) / initial_travel * 100):.1f}%")
        return order

    def generate_gcode(self):
        # Generate GCode from processed lines
        if not self.lines:
            if self.root.winfo_exists():
                messagebox.showwarning("Warning", "Convert SVG first")
            return
        try:
            speed = float(self.speed_entry.get())
            idle_speed = float(self.idle_speed_entry.get())
            power = int(self.power_entry.get())
            if speed <= 0 or idle_speed <= 0 or not (0 <= power <= 1000):
                raise ValueError("Invalid speed, idle speed, or power")
            self.config['laser_speed'] = speed
            self.config['idle_speed'] = idle_speed
            self.config['laser_power'] = power
            self.save_config()
        except ValueError as e:
            if self.root.winfo_exists():
                messagebox.showerror("Error", f"Invalid input values: {e}")
            return
        out_file = os.path.splitext(self.svg_filename)[0] + '.gcode'
        self.terminal.delete(1.0, tk.END)
        def log(msg):
            self.terminal.insert(tk.END, msg + '\n')
            self.terminal.see(tk.END)
            self.root.update_idletasks()
        self.log = log
        log("Starting GCode generation...")
        final_height = self.scaled_height
        lines = [((p1[0], final_height - p1[1]), (p2[0], final_height - p2[1])) for p1, p2 in self.lines]
        def is_close(p1, p2, eps_sq=1e-8):
            # Check if two points are close
            dx = p1[0] - p2[0]
            dy = p1[1] - p2[1]
            return dx*dx + dy*dy < eps_sq
        available = list(range(len(lines)))
        chains = []
        start_dict = {}
        end_dict = {}
        for i, line in enumerate(lines):
            start_dict.setdefault(line[0], []).append((i, False))
            end_dict.setdefault(line[1], []).append((i, True))
        while available:
            idx = available.pop(0)
            chain = [lines[idx][0], lines[idx][1]]
            current_end = chain[-1]
            while True:
                found = False
                candidates = start_dict.get(current_end, []) + end_dict.get(current_end, [])
                for cand_idx, is_reversed in candidates[:]:
                    if cand_idx in available:
                        available.remove(cand_idx)
                        cand_line = lines[cand_idx]
                        if is_reversed:
                            chain.append(cand_line[0])
                        else:
                            chain.append(cand_line[1])
                        current_end = chain[-1]
                        found = True
                        break
                if not found:
                    break
            current_start = chain[0]
            while True:
                found = False
                candidates = start_dict.get(current_start, []) + end_dict.get(current_start, [])
                for cand_idx, is_reversed in candidates[:]:
                    if cand_idx in available:
                        available.remove(cand_idx)
                        cand_line = lines[cand_idx]
                        if is_reversed:
                            chain.insert(0, cand_line[1])
                        else:
                            chain.insert(0, cand_line[0])
                        current_start = chain[0]
                        found = True
                        break
                if not found:
                    break
            chains.append(chain)
        log(f"Generated {len(chains)} continuous paths")
        opt_level = self.opt_var.get()
        max_iter = {'low': 5, 'medium': 10, 'high': 20}.get(opt_level, 0)
        if opt_level != 'none' and max_iter > 0:
            log(f"Optimizing chains with {opt_level} level...")
            chains = self.optimize_chains(chains, max_iter=max_iter)
        gcode_lines = []
        filename = os.path.basename(self.svg_filename)
        gcode_lines.append("; GCode generated from SVG")
        gcode_lines.append(f"; Original SVG: {filename}")
        gcode_lines.append(f"; Size: {self.scaled_width:.3f} x {self.scaled_height:.3f} mm")
        gcode_lines.append(f"; Cutting speed: {speed:.0f} mm/min, Idle speed: {idle_speed:.0f} mm/min, Power: {power}")
        gcode_lines.append("G21 ; Set mm mode")
        gcode_lines.append("G90 ; Set absolute positioning")
        gcode_lines.append("M5 ; Turn laser off")
        for i, chain in enumerate(chains):
            log(f"Writing path {i+1}/{len(chains)} with {len(chain)-1} segments")
            gcode_lines.append(f"; Path {i+1}")
            if len(chain) > 1:
                gcode_lines.append(f"G0 F{idle_speed:.0f} X{chain[0][0]:.3f} Y{chain[0][1]:.3f}")
                gcode_lines.append(f"M3 S{power}")
                pt = chain[1]
                gcode_lines.append(f"G1 F{speed:.0f} X{pt[0]:.3f} Y{pt[1]:.3f}")
                for pt in chain[2:]:
                    gcode_lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f}")
                gcode_lines.append("M5 ; Turn laser off")
        gcode_lines.append(f"G0 F{idle_speed:.0f} X0.0000 Y0.0000 ; Return to home")
        gcode_lines.append("M2 ; End program")
        try:
            with open(out_file, 'w') as f:
                f.write('\n'.join(gcode_lines) + '\n')
            log(f"GCode saved to: {out_file}")
        except Exception as e:
            log(f"Error writing GCode: {e}")
            if self.root.winfo_exists():
                messagebox.showerror("Error", f"Failed to write GCode: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
