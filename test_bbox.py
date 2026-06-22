import ezdxf
import os
import sys
import json
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
        # Check sheets bbox
        sheets = result.get('sheets', [])
        print(f'\nSheets: {len(sheets)}')
        for s in sheets:
            print(f'  Sheet {s["id"]}: bbox={s["bbox"]}, name={s["name"]}')
        
        # Check green_lines
        green_lines = result.get('green_lines', [])
        print(f'\nTotal green_lines: {len(green_lines)}')
        
        # Check DIM layer lines with bbox
        dim_lines = [gl for gl in green_lines if gl.get('layer', '').upper() == 'DIM']
        print(f'DIM layer lines: {len(dim_lines)}')
        
        # Check if DIM lines are within any sheet bbox
        for dl in dim_lines[:3]:
            start = dl['start']
            end = dl['end']
            print(f'\n  Line: start={start}, end={end}')
            for s in sheets:
                bbox = s['bbox']
                in_bbox = (
                    (bbox[0] <= start[0] <= bbox[2] and bbox[1] <= start[1] <= bbox[3]) or
                    (bbox[0] <= end[0] <= bbox[2] and bbox[1] <= end[1] <= bbox[3])
                )
                print(f'    Sheet {s["id"]} bbox={bbox}: in_bbox={in_bbox}')
