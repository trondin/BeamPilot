import sys
import os

def main():
    if len(sys.argv) < 3:
        print("Usage: python adj_speed.py input_file new_max_working [new_max_idle] [output_file]")
        sys.exit(1)

    input_file = sys.argv[1]
    try:
        new_max_working = float(sys.argv[2])
    except ValueError:
        print("Error: new_max_working must be a number.")
        sys.exit(1)

    arg_idx = 3
    new_max_idle = None
    if len(sys.argv) > arg_idx:
        try:
            new_max_idle = float(sys.argv[arg_idx])
            arg_idx += 1
        except ValueError:
            pass  # Next is output_file

    if len(sys.argv) > arg_idx:
        output_file = sys.argv[arg_idx]
    else:
        base, ext = os.path.splitext(input_file)
        output_file = base + '_speed' + ext

    # Read lines
    with open(input_file, 'r') as f:
        lines = f.readlines()

    # Find max_working and max_idle
    max_working = 0.0
    max_idle = 0.0
    laser_on = False
    for line in lines:
        if not line.strip():
            continue
        code_part = line.split(';', 1)[0]
        stripped_code = code_part.strip()
        if not stripped_code:
            continue
        if stripped_code.startswith('M3'):
            laser_on = True
        elif stripped_code.startswith('M5'):
            laser_on = False
        elif stripped_code.startswith(('G0', 'G1')):
            parts = stripped_code.split()
            f_val = None
            for p in parts:
                if p.startswith('F'):
                    try:
                        f_val = float(p[1:])
                    except ValueError:
                        pass
            if f_val is not None:
                cmd = parts[0]
                if cmd == 'G0' or not laser_on:
                    if f_val > max_idle:
                        max_idle = f_val
                elif cmd == 'G1' and laser_on:
                    if f_val > max_working:
                        max_working = f_val

    # If speeds not found, use provided or fallback
    if max_working == 0.0:
        max_working = new_max_working
    if max_idle == 0.0:
        max_idle = new_max_idle if new_max_idle is not None else new_max_working

    prop_working = new_max_working / max_working
    prop_idle = new_max_idle / max_idle if new_max_idle is not None else prop_working

    # Process the file and write output
    with open(output_file, 'w') as fout:
        laser_on = False
        first_g1_in_block = False
        last_was_m3 = False
        for line in lines:
            original_line = line
            if not line.strip():
                fout.write(original_line)
                continue

            # Split comment
            if ';' in line:
                code_part, comment = line.split(';', 1)
                comment = ';' + comment
            else:
                code_part = line
                comment = ''

            stripped_code = code_part.strip()
            if not stripped_code:
                fout.write(original_line)
                continue

            # Update laser state
            if stripped_code.startswith('M3'):
                laser_on = True
                first_g1_in_block = True
                last_was_m3 = True
            elif stripped_code.startswith('M5'):
                laser_on = False
                last_was_m3 = False
            elif stripped_code.startswith(('G0', 'G1')) and last_was_m3:
                first_g1_in_block = True
                last_was_m3 = False
            elif stripped_code.startswith(('G0', 'G1')):
                last_was_m3 = False
                if stripped_code.startswith('G1') and laser_on:
                    first_g1_in_block = False

            # Determine if needs modification
            new_code = None
            if stripped_code.startswith(('G0', 'G1')):
                prop = None
                convert_to_g0 = False
                ensure_f = False
                if stripped_code.startswith('G1') and not laser_on:
                    convert_to_g0 = True
                    prop = prop_idle
                    ensure_f = True
                elif stripped_code.startswith('G0'):
                    prop = prop_idle
                    ensure_f = True
                elif stripped_code.startswith('G1') and laser_on and first_g1_in_block:
                    prop = prop_working
                    ensure_f = True
                elif stripped_code.startswith('G1') and laser_on:
                    prop = prop_working
                    ensure_f = False  # Only first G1 in block needs F

                if prop is not None:
                    # Calculate leading and trailing
                    leading = code_part[:len(code_part) - len(code_part.lstrip())]
                    temp = code_part.lstrip()
                    trailing = temp[len(stripped_code):]

                    # Modify parts
                    parts = stripped_code.split()
                    new_parts = [parts[0]]
                    if convert_to_g0:
                        new_parts[0] = 'G0'
                    has_f = False
                    for p in parts[1:]:
                        if p.startswith('F'):
                            try:
                                old_f = float(p[1:])
                                new_f = old_f * prop
                                new_parts.append(f'F{new_f:.2f}')
                                has_f = True
                            except ValueError:
                                new_parts.append(p)
                        else:
                            new_parts.append(p)
                    # Ensure F parameter if needed
                    if ensure_f and not has_f:
                        new_parts.append(f'F{new_max_idle if new_parts[0] == "G0" or not laser_on else new_max_working:.2f}')
                    new_stripped = ' '.join(new_parts)

                    new_code = leading + new_stripped + trailing

            if new_code is not None:
                fout.write(new_code + comment)
            else:
                fout.write(original_line)

if __name__ == "__main__":
    main()
