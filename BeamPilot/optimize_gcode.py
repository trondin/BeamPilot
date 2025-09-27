#!/usr/bin/env python3
"""
optimize_gcode.py

Reorders cutting segments in G-code to minimize idle travel.
- Cutting segment = sequence of G1 commands (segment content unchanged, only order and optional reversal).
- Preserves file prologue and epilogue.
- Uses fast greedy algorithm with local improvements (swap + reversal).
- Handles both G0 for idle moves and M5 + G1 for idle moves (laser mode).

Usage:
    python3 optimize_gcode.py input.gcode [output.gcode] [--level 0|1|2]
"""

import sys
import re
from math import hypot
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse

# --------------- Parsing ---------------

G_MOVE_RE = re.compile(r'^(G0|G00|G1|G01)\b', re.IGNORECASE)
COORD_RE = re.compile(r'([XY])\s*([+-]?\d+\.?\d*)', re.IGNORECASE)
F_RE = re.compile(r'F\s*([+-]?\d+\.?\d*)', re.IGNORECASE)
G90_RE = re.compile(r'\bG90\b', re.IGNORECASE)
G91_RE = re.compile(r'\bG91\b', re.IGNORECASE)
M3_RE = re.compile(r'\bM3\b', re.IGNORECASE)
M5_RE = re.compile(r'\bM5\b', re.IGNORECASE)

HUGE_FILE = 10000
BIG_FILE = 3000

def is_g_move(line):
    """Quick check for G-code movement command"""
    stripped = line.strip().upper()
    return bool(G_MOVE_RE.match(stripped))

def parse_gcode_lines(lines):
    """
    Splits G-code file into preamble, list of segments (each segment is a dict with 'lines' and 'points'),
    and epilogue.
    Segment = sequence of G1 commands (including lines with G1 and other parameters).
    Maintains absolute coordinates (converts from relative if needed).
    Handles laser mode (M3/M5 with G1 idle) as a variant.
    """
    preamble = []
    epilogue = []
    segments = []

    current_pos = {'X': 0.0, 'Y': 0.0}
    current_F = None
    absolute = True  # Assume absolute coordinates by default
    laser_mode = False
    laser_on = False  # Initially off
    in_segment = False
    seg_lines = []
    seg_points = []

    first_cut_seen = False
    last_line_idx_of_cut = -1
    idle_F = 3000.0  # Default idle feedrate for laser mode

    for idx, raw in enumerate(lines):
        line = raw.rstrip('\n')
        stripped = line.strip()
        upper = stripped.upper()

        # Update modal absolute/relative if found
        if G90_RE.search(upper):
            absolute = True
        if G91_RE.search(upper):
            absolute = False

        # Strip inline comment after ';' (keep full original line for output)
        no_comment = stripped
        if ';' in stripped:
            no_comment = stripped.split(';', 1)[0].strip()

        # Check for M3/M5
        if M3_RE.search(upper):
            laser_mode = True
            laser_on = True
            if not in_segment:
                in_segment = True
                seg_lines = [line]
                seg_points = [(current_pos['X'], current_pos['Y'])]
                first_cut_seen = True
            else:
                if in_segment:
                    seg_lines.append(line)
            continue

        if M5_RE.search(upper):
            laser_mode = True
            laser_on = False
            if in_segment:
                seg_lines.append(line)
                segments.append({'lines': seg_lines, 'points': seg_points})
                in_segment = False
                seg_lines = []
                seg_points = []
            continue

        # Quick check for G-code movement command
        if is_g_move(no_comment):
            move = G_MOVE_RE.match(no_comment.upper()).group(1).upper()
            coords = {m.group(1).upper(): float(m.group(2)) for m in COORD_RE.finditer(no_comment)}
            f_match = F_RE.search(no_comment)
            if f_match:
                current_F = float(f_match.group(1))

            is_idle = (move in ('G0', 'G00')) or (laser_mode and not laser_on and move in ('G1', 'G01'))

            if is_idle:
                # Idle move
                if in_segment:
                    segments.append({'lines': seg_lines, 'points': seg_points})
                    in_segment = False
                    seg_lines = []
                    seg_points = []
                # Update current position
                new_x = current_pos['X']
                new_y = current_pos['Y']
                if 'X' in coords:
                    new_x = coords['X'] if absolute else current_pos['X'] + coords['X']
                if 'Y' in coords:
                    new_y = coords['Y'] if absolute else current_pos['Y'] + coords['Y']
                current_pos['X'] = new_x
                current_pos['Y'] = new_y
                if current_F is not None:
                    idle_F = current_F  # Update idle feedrate from file
                if not first_cut_seen:
                    preamble.append(line)
                continue
            else:
                # Cutting move (G1 and (not laser_mode or laser_on))
                if not in_segment:
                    in_segment = True
                    first_cut_seen = True
                    seg_lines = []
                    seg_points = [(current_pos['X'], current_pos['Y'])]
                # Compute new position
                new_x = current_pos['X']
                new_y = current_pos['Y']
                if 'X' in coords:
                    new_x = coords['X'] if absolute else current_pos['X'] + coords['X']
                if 'Y' in coords:
                    new_y = coords['Y'] if absolute else current_pos['Y'] + coords['Y']

                # Append line and new point
                seg_lines.append(line)
                seg_points.append((new_x, new_y))
                current_pos['X'] = new_x
                current_pos['Y'] = new_y
                last_line_idx_of_cut = idx
                continue

        # Non-move lines (not M3/M5, handled above)
        if in_segment:
            seg_lines.append(line)
        else:
            if not first_cut_seen:
                preamble.append(line)
            else:
                epilogue.append(line)

    # Close open segment at EOF
    if in_segment and seg_lines:
        segments.append({'lines': seg_lines, 'points': seg_points})

    return preamble, segments, epilogue, laser_mode, idle_F

# -------------- Optimization Utilities --------------

def dist(a, b):
    """Calculate Euclidean distance between two points"""
    return hypot(a[0] - b[0], a[1] - b[1])

def dist_sq(a, b):
    """Calculate squared distance for faster comparisons"""
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx*dx + dy*dy

def total_travel(ordered_segments):
    """Calculate total travel distance between segments"""
    if not ordered_segments:
        return 0.0
    total = 0.0
    for i in range(len(ordered_segments) - 1):
        a = ordered_segments[i]['points'][-1]
        b = ordered_segments[i+1]['points'][0]
        total += dist(a, b)
    return total

# -------------- Order Optimization --------------

def greedy_order_with_reversal_fast(segments):
    """Fast greedy algorithm with precomputed endpoints"""
    if not segments:
        return []

    unused = segments[:]
    ordered = [unused.pop(0)]
    
    # Precompute all segment endpoints
    endpoints = []
    for seg in unused:
        endpoints.append((seg['points'][0], seg['points'][-1]))
    
    total_segments = len(segments)
    
    while unused:
        if len(ordered) % 100 == 0:
            print(f"Greedy progress: {len(ordered)} / {total_segments}")
            
        last_end = ordered[-1]['points'][-1]
        best_idx = 0
        best_orient = False
        best_d_sq = float('inf')
        
        for i, (start, end) in enumerate(endpoints):
            d_start_sq = dist_sq(last_end, start)
            d_end_sq = dist_sq(last_end, end)
            
            if d_start_sq < best_d_sq:
                best_d_sq = d_start_sq
                best_idx = i
                best_orient = False
            if d_end_sq < best_d_sq:
                best_d_sq = d_end_sq
                best_idx = i
                best_orient = True
        
        # Update endpoints and move segment
        seg = unused.pop(best_idx)
        endpoints.pop(best_idx)
        
        if best_orient:
            seg = {
                'points': seg['points'][::-1],
                'lines': seg['lines'][::-1]
            }
        
        ordered.append(seg)
    
    return ordered

def optimize_orientation(order, i, j):
    """Optimize orientation between two adjacent segments"""
    if j >= len(order):
        return
    
    prev_end = order[i]['points'][-1]
    seg = order[j]
    
    d0 = dist(prev_end, seg['points'][0])
    d1 = dist(prev_end, seg['points'][-1])
    
    if d1 < d0:
        order[j] = {
            'points': seg['points'][::-1],
            'lines': seg['lines'][::-1]
        }

def fast_local_improve(order, max_attempts=500):
    """Fast local improvement with random swaps and reversals"""
    n = len(order)
    if n < 3:
        return order, False
    
    current_score = total_travel(order)
    improved = False
    
    for attempt in range(max_attempts):
        i = random.randint(0, n-2)
        j = random.randint(i+1, n-1)
        
        # Create new sequence
        new_order = order.copy()
        
        # Randomly choose mutation type
        if random.random() < 0.7:  # 70% swap, 30% reverse
            new_order[i], new_order[j] = new_order[j], new_order[i]
        else:
            new_order[i:j+1] = new_order[i:j+1][::-1]
        
        # Optimize orientation around modified area
        start_idx = max(0, i-1)
        end_idx = min(n, j+2)
        
        for k in range(start_idx + 1, end_idx):
            if k < n:
                optimize_orientation(new_order, k-1, k)
        
        new_score = total_travel(new_order)
        
        if new_score < current_score - 1e-9:
            order = new_order
            current_score = new_score
            improved = True
            print(f"Local improvement found: {new_score:.3f}")
    
    return order, improved

def parallel_local_improve(order, num_threads=4, max_attempts_per_thread=200):
    """Parallel local improvement with multiple threads"""
    n = len(order)
    if n < 3:
        return order, False
    
    def try_improvement(thread_id):
        local_order = order.copy()
        local_improved = False
        local_best_score = total_travel(order)
        
        for attempt in range(max_attempts_per_thread):
            i = random.randint(0, n-2)
            j = random.randint(i+1, n-1)
            
            # Apply mutation
            if random.random() < 0.7:
                local_order[i], local_order[j] = local_order[j], local_order[i]
            else:
                local_order[i:j+1] = local_order[i:j+1][::-1]
            
            # Optimize orientation
            start_idx = max(0, i-1)
            end_idx = min(n, j+2)
            for k in range(start_idx + 1, end_idx):
                if k < n:
                    optimize_orientation(local_order, k-1, k)
            
            new_score = total_travel(local_order)
            
            if new_score < local_best_score - 1e-9:
                local_best_score = new_score
                local_improved = True
                break
        
        return local_order, local_improved
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(try_improvement, i) for i in range(num_threads)]
        
        best_order = order
        best_improved = False
        best_score = total_travel(order)
        
        for future in as_completed(futures):
            result, improved = future.result()
            if improved:
                result_score = total_travel(result)
                if result_score < best_score:
                    best_order = result
                    best_score = result_score
                    best_improved = True
        
        return best_order, best_improved

def optimize_segments(segments, level=None, max_iter=20, max_time=180):
    """Optimized segment reordering with configurable optimization level"""
    if not segments:
        return []

    print(f"Segments found: {len(segments)}. Running optimization...")

    # Determine optimization level if not specified
    if level is None:
        if len(segments) > HUGE_FILE:
            level = 0
        elif len(segments) > BIG_FILE:
            level = 1
        else:
            level = 2

    print(f"Optimization level: {level}")

    # Level 0: Fast greedy only
    if level == 0:
        print("Using fast greedy algorithm only")
        order = greedy_order_with_reversal_fast(segments)
        return order

    # Level 1: Greedy + parallel local improvements
    # Level 2: Greedy + iterative local improvements
    order = greedy_order_with_reversal_fast(segments)
    initial_travel = total_travel(order)
    print(f"Initial greedy travel: {initial_travel:.3f}")

    # Local improvements
    iter_num = 0
    global_start = time.time()
    improved = True

    while iter_num < max_iter and improved:
        if time.time() - global_start > max_time:
            print("Optimization timed out.")
            break
            
        iter_num += 1
        print(f"Starting improvement iteration {iter_num}")
        
        if level == 1:
            order, improved = parallel_local_improve(order)
        else:  # level == 2
            order, improved = fast_local_improve(order)
        
        if improved:
            current_travel = total_travel(order)
            print(f"Iteration {iter_num}: travel = {current_travel:.3f}")

    final_travel = total_travel(order)
    print(f"Optimization done in {iter_num} iterations. Final travel = {final_travel:.3f}")
    # Avoid division by zero when initial_travel is 0 (e.g., single segment)
    improvement = 0.0 if initial_travel == 0 else ((initial_travel - final_travel) / initial_travel * 100)
    print(f"Improvement: {improvement:.1f}%")
    
    return order

# -------------- G-code Generation --------------

def generate_gcode(preamble, ordered_segments, epilogue, laser_mode, idle_F):
    """
    Generates optimized G-code:
    - Writes preamble
    - Adds idle moves to segment start points (G0 or M5 + G1 F<idle_F>)
    - Outputs original segment lines (including M3/M5, etc.)
    - Appends epilogue
    """
    out = []
    current_pos = (None, None)

    out.extend(preamble)

    for seg in ordered_segments:
        seg_start = seg['points'][0]
        if current_pos[0] is None or (abs(current_pos[0] - seg_start[0]) > 1e-6 or abs(current_pos[1] - seg_start[1]) > 1e-6):
            if not laser_mode:
                out.append(f"G0 X{seg_start[0]:.4f} Y{seg_start[1]:.4f}")
            else:
                out.append("M5")
                out.append(f"G1 F{idle_F:.1f} X{seg_start[0]:.4f} Y{seg_start[1]:.4f}")
        out.extend(seg['lines'])
        current_pos = seg['points'][-1]

    out.extend(epilogue)
    return '\n'.join(out) + '\n'

# ---------------- Main ----------------

def main():
    parser = argparse.ArgumentParser(description="Optimize G-code to minimize idle travel")
    parser.add_argument("input", help="Input G-code file")
    parser.add_argument("output", nargs='?', default="optimized.gcode", help="Output G-code file")
    parser.add_argument("--level", type=int, choices=[0, 1, 2], help="Optimization level: 0 (minimal), 1 (medium), 2 (maximum)")
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output
    opt_level = args.level

    print("Reading and parsing G-code...")
    start_time = time.time()
    
    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    parse_time = time.time()
    preamble, segments, epilogue, laser_mode, idle_F = parse_gcode_lines(lines)
    parse_time = time.time() - parse_time
    
    print(f"Parsed in {parse_time:.2f}s: {len(preamble)} preamble, {len(segments)} segments, {len(epilogue)} epilogue")
    print(f"Laser mode detected: {laser_mode}")

    if not segments:
        print("No cutting segments found. Writing original file.")
        with open(output_path, 'w', encoding='utf-8') as fw:
            fw.writelines(lines)
        return

    # Optimization
    opt_time = time.time()
    ordered = optimize_segments(segments, level=opt_level)
    opt_time = time.time() - opt_time
    print(f"Optimization completed in {opt_time:.2f}s")

    # Generate result
    gen_time = time.time()
    optimized_text = generate_gcode(preamble, ordered, epilogue, laser_mode, idle_F)
    gen_time = time.time() - gen_time
    
    with open(output_path, 'w', encoding='utf-8') as fw:
        fw.write(optimized_text)

    total_time = time.time() - start_time
    print(f"Total time: {total_time:.2f}s")
    print(f"Optimized G-code written to {output_path}")

if __name__ == "__main__":
    main()
