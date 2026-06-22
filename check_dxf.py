import ezdxf
import os

# Find the file with '2' in name
target_file = None
for f in os.listdir('data'):
    if f.endswith('.dxf') and '2' in f and '가나' in f:
        target_file = os.path.join('data', f)
        print(f'Found: {f}')
        break

if not target_file:
    # Try any file with '2'
    for f in os.listdir('data'):
        if f.endswith('.dxf') and '2' in f:
            target_file = os.path.join('data', f)
            print(f'Fallback: {f}')
            break

if target_file:
    doc = ezdxf.readfile(target_file, encoding='ascii')
    msp = doc.modelspace()
    
    # Count all entities by layer
    layer_entities = {}
    for e in msp:
        layer = e.dxf.layer
        if layer not in layer_entities:
            layer_entities[layer] = []
        layer_entities[layer].append(e.dxftype())
    
    print('\n=== Entities by Layer ===')
    for layer, types in sorted(layer_entities.items()):
        print(f'{layer}: {len(types)} entities')
        type_counts = {}
        for t in types:
            type_counts[t] = type_counts.get(t, 0) + 1
        for t, c in type_counts.items():
            print(f'  - {t}: {c}')
    
    # Check Defpoints specifically
    print('\n=== Defpoints Layer Details ===')
    for e in msp:
        if 'defpoint' in e.dxf.layer.lower():
            print(f'  {e.dxftype()} handle={e.dxf.handle}')
            if e.dxftype() == 'LWPOLYLINE':
                pts = list(e.vertices())
                print(f'    vertices={len(pts)}, closed={e.closed}')
            elif e.dxftype() == 'LINE':
                print(f'    start={e.dxf.start}, end={e.dxf.end}')
    
    # Check DIMENSION
    print('\n=== DIMENSION Details ===')
    for e in msp.query('DIMENSION'):
        print(f'  layer={e.dxf.layer}, text={e.dxf.get("text_override","")}, meas={e.dxf.get("actual_measurement",0)}')
        dp = e.dxf.get('defpoint')
        dp2 = e.dxf.get('defpoint2')
        print(f'    defpoint={dp}, defpoint2={dp2}')
