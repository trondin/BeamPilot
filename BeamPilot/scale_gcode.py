import re
import sys

"""
G-code Scaling Utility

This program scales a G-code model to fit within specified maximum dimensions
while maintaining aspect ratio and positioning the result in the bottom-left corner.

How it works:
1. Reads input G-code file and extracts current dimensions
2. Normalizes coordinates (shifts to positive quadrant if needed)
3. Calculates scaling factor based on maximum allowed X/Y dimensions
4. Applies scaling and positions the model in the bottom-left corner
5. Saves result to a specified output file or with 'scaled_' prefix if not specified
"""

def parse_arguments():
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print("Usage: python scale_gcode.py <input_file> <max_x> <max_y> [output_file]")
        sys.exit(1)
    input_file = sys.argv[1]
    max_x = float(sys.argv[2])
    max_y = float(sys.argv[3])
    output_file = sys.argv[4] if len(sys.argv) == 5 else f"scaled_{input_file}"
    return input_file, max_x, max_y, output_file

def read_gcode(filename):
    with open(filename, 'r') as f:
        return f.readlines()

def extract_dimensions(gcode_lines):
    x_vals, y_vals = [], []
    pattern = re.compile(r'([XY])(-?\d+\.?\d*)')
    
    for line in gcode_lines:
        matches = pattern.findall(line)
        x, y = None, None
        for axis, value in matches:
            if axis == 'X':
                x = float(value)
            elif axis == 'Y':
                y = float(value)
        if x is not None:
            x_vals.append(x)
        if y is not None:
            y_vals.append(y)
    
    if not x_vals or not y_vals:
        print("Error: X and/or Y coordinates not found in G-code")
        sys.exit(1)
    
    return min(x_vals), max(x_vals), min(y_vals), max(y_vals)

def normalize_coordinates(gcode_lines, x_offset, y_offset):
    normalized_lines = []
    coord_pattern = re.compile(r'([XY])(-?\d+\.?\d*)')
    
    for line in gcode_lines:
        def normalize_match(match):
            axis = match.group(1)
            value = float(match.group(2))
            if axis == 'X':
                new_val = value + x_offset
            else:
                new_val = value + y_offset
            return f"{axis}{new_val:.6f}"
        
        normalized_line = coord_pattern.sub(normalize_match, line)
        normalized_lines.append(normalized_line)
    
    return normalized_lines

def scale_gcode(gcode_lines, scale_factor, x_offset, y_offset):
    scaled_lines = []
    coord_pattern = re.compile(r'([XY])(-?\d+\.?\d*)')
    
    for line in gcode_lines:
        def scale_match(match):
            axis = match.group(1)
            value = float(match.group(2))
            if axis == 'X':
                new_val = value * scale_factor + x_offset
            else:
                new_val = value * scale_factor + y_offset
            return f"{axis}{new_val:.6f}"
        
        scaled_line = coord_pattern.sub(scale_match, line)
        scaled_lines.append(scaled_line)
    
    return scaled_lines

def main():
    input_file, max_x, max_y, output_file = parse_arguments()
    gcode_lines = read_gcode(input_file)
    
    min_x, max_x_orig, min_y, max_y_orig = extract_dimensions(gcode_lines)
    
    # Normalize coordinates (make all positive)
    x_offset = -min_x if min_x < 0 else 0
    y_offset = -min_y if min_y < 0 else 0
    
    if x_offset != 0 or y_offset != 0:
        print(f"Normalizing coordinates: X offset {x_offset:.2f}, Y offset {y_offset:.2f}")
        gcode_lines = normalize_coordinates(gcode_lines, x_offset, y_offset)
        # Update boundaries after normalization
        min_x, max_x_orig, min_y, max_y_orig = extract_dimensions(gcode_lines)
    
    width_orig = max_x_orig - min_x
    height_orig = max_y_orig - min_y

    print(f"Normalized model dimensions: {width_orig:.2f} x {height_orig:.2f}")
    print(f"Machine maximum dimensions: {max_x:.2f} x {max_y:.2f}")

    scale_x = max_x / width_orig
    scale_y = max_y / height_orig
    scale_factor = min(scale_x, scale_y)

    new_width = width_orig * scale_factor
    new_height = height_orig * scale_factor
    # Position in bottom-left corner
    x_offset = 0  # Left edge (X=0)
    y_offset = 0  # Bottom edge (Y=0)

    print(f"Scaling factor: {scale_factor:.6f}")
    print(f"New dimensions: {new_width:.2f} x {new_height:.2f}")
    print(f"Position: Bottom-left corner (X offset: {x_offset:.2f}, Y offset: {y_offset:.2f})")

    scaled_gcode = scale_gcode(gcode_lines, scale_factor, x_offset, y_offset)
    
    with open(output_file, 'w') as f:
        f.writelines(scaled_gcode)
    
    print(f"Scaling completed. Result saved to {output_file}")

if __name__ == "__main__":
    main()
