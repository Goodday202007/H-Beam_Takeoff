import ezdxf
import os

target_file = None
for f in os.listdir('data'):
    if f.endswith('.dxf') and '2' in f and '가나' in f:
        target_file = os.path.join('data', f)
        break

if target_file:
    doc = ezdxf.readfile(target_file, encoding='ascii')
    msp = doc.modelspace()
    
    print('=== DIM Layer LWPOLYLINE Details ===')
    for e in msp:
        if e.dxf.layer == 'DIM' and e.dxftype() == 'LWPOLYLINE':
            pts = list(e.vertices())
            if len(pts) >= 2:
                p1, p2 = pts[0], pts[-1]
                dx = abs(p2[0] - p1[0])
                dy = abs(p2[1] - p1[1])
                is_vertical = dx < 50 and dy > 100
                is_horizontal = dy < 50 and dx > 100
                print(f'  handle={e.dxf.handle}, vertices={len(pts)}, closed={e.closed}')
                print(f'    start={p1}, end={p2}')
                print(f'    dx={dx:.1f}, dy={dy:.1f}, vertical={is_vertical}, horizontal={is_horizontal}')
    
    print('\n=== AZ-DIML Layer DIMENSION Details ===')
    for e in msp.query('DIMENSION'):
        if e.dxf.layer == 'AZ-DIML':
            print(f'  handle={e.dxf.handle}')
            # Try to get measurement
            try:
                meas = e.dxf.actual_measurement
                print(f'    measurement={meas}')
            except:
                pass
            # Try to get defpoints
            try:
                dp = e.dxf.defpoint
                dp2 = e.dxf.defpoint2
                print(f'    defpoint={dp}, defpoint2={dp2}')
            except:
                pass
