import ezdxf
import os
import sys
sys.path.insert(0, '.')
from takeoff_analysis import analyze_dxf_json

# Find the file
target_file = None
for f in os.listdir('data'):
    if f.endswith('.dxf') and '2' in f and '가나' in f:
        target_file = os.path.join('data', f)
        break

if target_file:
    print(f'Analyzing: {target_file}')
    result = analyze_dxf_json(target_file)
    
    if 'error' in result:
        print(f'Error: {result["error"]}')
    else:
        # Check green_lines
        green_lines = result.get('green_lines', [])
        print(f'\nTotal green_lines: {len(green_lines)}')
        
        # Count by type
        type_counts = {}
        for gl in green_lines:
            t = gl.get('type', 'unknown')
            type_counts[t] = type_counts.get(t, 0) + 1
        print('By type:', type_counts)
        
        # Count by layer
        layer_counts = {}
        for gl in green_lines:
            l = gl.get('layer', 'unknown')
            layer_counts[l] = layer_counts.get(l, 0) + 1
        print('By layer:', layer_counts)
        
        # Show DIM layer lines
        dim_lines = [gl for gl in green_lines if gl.get('layer', '').upper() == 'DIM']
        print(f'\nDIM layer lines: {len(dim_lines)}')
        for dl in dim_lines[:5]:
            print(f'  {dl}')
