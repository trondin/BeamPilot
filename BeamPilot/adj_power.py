import sys
import os
import re

def main():
    if len(sys.argv) < 3:
        print("Usage: python adj_power.py input_file new_max_power [output_file]")
        sys.exit(1)

    input_file = sys.argv[1]
    try:
        new_max = int(sys.argv[2])
    except ValueError:
        print("Error: new_max_power must be an integer.")
        sys.exit(1)

    if len(sys.argv) == 4:
        output_file = sys.argv[3]
    else:
        base, ext = os.path.splitext(input_file)
        output_file = base + '_power' + ext

    # Find the current max S in M3 commands
    max_s = 0
    lines = []
    m3_found = False
    
    try:
        with open(input_file, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found.")
        sys.exit(1)
    
    print("Scanning for M3 commands...")
    for i, line in enumerate(lines):
        # Ищем M3 команды в каждой строке
        if 'M3' in line:
            m3_found = True
            match = re.search(r'M3\s*S(\d+)', line)
            if match:
                s_val = int(match.group(1))
                if s_val > max_s:
                    max_s = s_val
                    print(f"Found M3 at line {i+1} with S{s_val}")

    if not m3_found:
        print("Error: No M3 commands found in the file.")
        sys.exit(1)
    if max_s == 0:
        print("Error: No valid S values found in M3 commands.")
        sys.exit(1)

    print(f"Maximum S value found: {max_s}")
    proportion = new_max / max_s
    print(f"Proportion for scaling: {proportion:.2f}")

    # Process the file and write output
    try:
        with open(output_file, 'w') as fout:
            laser_on = False  # Track laser state
            
            for i, line in enumerate(lines):
                original_line = line
                
                # Update laser state
                if 'M3' in line:
                    laser_on = True
                elif 'M5' in line:
                    laser_on = False
                
                # Check for erroneous idle move pattern: M5, G1, M3
                if (i > 0 and i + 1 < len(lines) and
                    'M5' in lines[i-1] and
                    line.strip().startswith('G1') and
                    'M3' in lines[i+1]):
                    # Convert G1 to G0 - preserve original formatting
                    new_line = line.replace('G1', 'G0', 1)
                    fout.write(new_line)
                    continue
                
                # Replace G1 with G0 when laser is off (simple case)
                if not laser_on and line.strip().startswith('G1'):
                    new_line = line.replace('G1', 'G0', 1)
                    fout.write(new_line)
                # Scale S parameter in M3 commands
                elif 'M3' in line:
                    # Use regex to find and replace S parameter
                    def replace_s(match):
                        old_s = int(match.group(1))
                        new_s = round(old_s * proportion)
                        return f'S{new_s}'
                    
                    new_line = re.sub(r'S(\d+)', replace_s, line)
                    fout.write(new_line)
                else:
                    # Write original line with all formatting preserved
                    fout.write(original_line)
                    
    except IOError as e:
        print(f"Error writing output file: {e}")
        sys.exit(1)

    print(f"Output written to {output_file}")

if __name__ == "__main__":
    main()
