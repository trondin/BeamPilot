#!/usr/bin/env python3
"""
G-code power control fix script
Usage: python fix_power.py input_file [power] [output_file]
"""

import sys
import os

def fix_gcode_power(input_file, power=255, output_file=None):
    """
    Fixes G-code by adding laser power control commands
    
    Args:
        input_file: path to input file
        power: laser power (0-255)
        output_file: path to output file (if None, generated automatically)
    """
    
    # Generate output filename if not specified
    if output_file is None:
        base_name, ext = os.path.splitext(input_file)
        output_file = f"{base_name}_fixed{ext}"
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        # Try different encoding if UTF-8 fails
        with open(input_file, 'r', encoding='latin-1') as f:
            lines = f.readlines()
    
    fixed_lines = []
    i = 0
    n = len(lines)
    
    while i < n:
        line = lines[i].strip()
        
        # If current line is G0 (travel move)
        if line.startswith('G0'):
            # Find start of G0 sequence
            g0_start = i
            
            # Find end of G0 sequence
            while i < n and (lines[i].strip().startswith('G0') or lines[i].strip() == ''):
                i += 1
            
            # Add M5 before first G0 line
            first_g0_line = lines[g0_start]
            # Preserve original line indentation
            indent = first_g0_line[:len(first_g0_line) - len(first_g0_line.lstrip())]
            fixed_lines.append(f"{indent}M5\n")
            fixed_lines.append(first_g0_line)
            
            # Add remaining G0 lines
            for j in range(g0_start + 1, i):
                fixed_lines.append(lines[j])
            
            # Add M3 S### after last G0 line
            if i < n:  # If there's a next line after G0
                # Check if next line is already a laser command
                next_line = lines[i].strip()
                if not (next_line.startswith('M3') or next_line.startswith('M106') or 
                       next_line.startswith('M107') or next_line.startswith('M5')):
                    # Preserve next line's indentation
                    next_indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
                    fixed_lines.append(f"{next_indent}M3 S{power}\n")
            
        else:
            # If line is not G0, copy it as is
            fixed_lines.append(lines[i])
            i += 1
    
    # Write fixed code to output file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)
    
    print(f"File fixed: {output_file}")
    print(f"Laser power set to: S{power}")

def main():
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Usage: python fix_power.py input_file [power] [output_file]")
        print("  input_file  - input G-code file")
        print("  power       - laser power (0-255, default: 255)")
        print("  output_file - output file (default: name_fixed.ext)")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"Error: file '{input_file}' not found")
        sys.exit(1)
    
    # Process power parameter
    power = 255
    if len(sys.argv) >= 3:
        try:
            power = int(sys.argv[2])
            if not (0 <= power <= 255):
                print("Warning: power must be between 0-255, using 255")
                power = 255
        except ValueError:
            print("Error: power must be an integer")
            sys.exit(1)
    
    # Process output file parameter
    output_file = None
    if len(sys.argv) >= 4:
        output_file = sys.argv[3]
    
    try:
        fix_gcode_power(input_file, power, output_file)
    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
