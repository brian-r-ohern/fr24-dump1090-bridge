"""Positive/negative synthetic geometries and engine lifecycle checks."""
import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from motion_patterns import detect,project,phases,LIMITS
from motion_state import MotionEngine
EARTH=6371008.8;BASE=1700000000.

def sample(t,x,y,ground=False):
 return dict(t=BASE+t,lat=42+math.degrees(y/EARTH),lon=-77+math.degrees(x/EARTH/math.cos(math.radians(42))),ground=ground)

def orbit(turns=2.2,radius=10000,rate=1,sign=1,stretch=1,drift=0):
 duration=int(turns*360/rate)
 return [sample(t,radius*math.cos(math.radians(t*rate*sign))+drift*t,radius*stretch*math.sin(math.radians(t*rate*sign))) for t in range(0,duration+1,10)]

def racetrack(cycles=2.2,length=20000,radius=5000,speed=150):
 perimeter=2*length+2*math.pi*radius;duration=int(cycles*perimeter/speed)
 result=[]
 for t in range(0,duration+1,10):
  d=t*speed%perimeter
  if d<length:x,y=d,0
  elif d<length+math.pi*radius:
   angle=math.pi/2-(d-length)/radius;x,y=length+radius*math.cos(angle),-radius+radius*math.sin(angle)
  elif d<2*length+math.pi*radius:x,y=2*length+math.pi*radius-d,-2*radius
  else:
   angle=-math.pi/2-(d-2*length-math.pi*radius)/radius;x,y=radius*math.cos(angle),-radius+radius*math.sin(angle)
  result.append(sample(t,x,y))
 return result

class PatternTests(unittest.TestCase):
 def test_repeated_orbits_both_directions_and_partial_turn(self):
  for sign in (-1,1):
   result=detect(orbit(sign=sign));self.assertEqual(result[0]['name'],'repeated_orbit');self.assertEqual(result[0]['status'],'established')
   self.assertEqual(result[0]['evidence']['completed_orbits'],2)
   self.assertFalse(result[0]['confidence_is_calibrated'])
  self.assertEqual(detect(orbit(.4))[0]['name'],'constant_radius_turn')
  self.assertEqual(detect(orbit(1.2))[0]['name'],'orbit')
 def test_straight_ellipse_drift_and_ground_are_not_repeated_orbits(self):
  self.assertEqual(detect([sample(t,t*150,0) for t in range(0,1000,10)]),[])
  for data in (orbit(stretch=2),orbit(drift=100)):
   self.assertFalse(any(p['name']=='repeated_orbit' for p in detect(data)))
  data=orbit();data[-1]['ground']=True;self.assertEqual(detect(data),[])
 def test_repeated_racetrack_and_large_50nm_legs(self):
  for length in (20000,92600):
   data=racetrack(length=length)
   self.assertLess(data[-1]['t']-data[0]['t'],3600)
   result=detect(data);self.assertTrue(result,phases(project(data)))
   self.assertEqual(result[0]['name'],'racetrack');self.assertEqual(result[0]['status'],'established')
   self.assertTrue(result[0]['evidence']['centroid_repeat_verified'])
 def test_orbit_exit_and_reversal(self):
  data=orbit();last=data[-1];x=10000*math.cos(math.radians((last['t']-BASE)));y=10000*math.sin(math.radians((last['t']-BASE)))
  for dt in range(10,131,10):data.append(sample(last['t']-BASE+dt,x+dt*170,y))
  self.assertFalse(any(p['name'] in ('orbit','repeated_orbit','constant_radius_turn') for p in detect(data)))
  data=orbit(.5);last=data[-1]
  for dt in range(10,51,10):data.append(sample(last['t']-BASE+dt,-10000,-170*dt))
  self.assertEqual(detect(data)[0]['name'],'course_reversal')
 def test_racetrack_candidate_then_exit_and_drifting_negative(self):
  first=detect(racetrack(cycles=1.2))
  self.assertEqual(first[0]['name'],'racetrack');self.assertEqual(first[0]['status'],'candidate')
  data=racetrack(cycles=2.2);last=data[-1]
  # Leave the observed corridor for well over the exit interval.
  for dt in range(10,601,10):
   data.append(dict(last,t=last['t']+dt,lat=last['lat']+dt*.001))
  self.assertFalse(any(p['name']=='racetrack' for p in detect(data)))
  drifting=racetrack(cycles=2.2)
  for p in drifting:p['lon']+=(p['t']-BASE)*.0005
  self.assertFalse(any(p['name']=='racetrack' and p['status']=='established' for p in detect(drifting)))
 def test_antimeridian_and_small_position_noise(self):
  data=orbit();origin=data[0]['lon']
  for p in data:p['lon']=((p['lon']-origin+179.99)+180)%360-180
  self.assertEqual(detect(data)[0]['name'],'repeated_orbit')
  data=orbit()
  for i,p in enumerate(data):p['lat']+=.00001*math.sin(i*1.7)
  self.assertEqual(detect(data)[0]['name'],'repeated_orbit')
 def test_hour_history_is_bounded_and_excluded_sources_stay_excluded(self):
  now=[BASE];engine=MotionEngine('sbs_30003',clock=lambda:now[0])
  for t in range(0,7201,10):
   p=sample(t,100*t,0);now[0]=p['t']
   engine.observe([dict(hex='a',lat=p['lat'],lon=p['lon'],alt_baro=10000)],now[0],now[0],{'a':{'position_time':p['t']}})
  self.assertLessEqual(engine.status()['retained_pattern_samples'],360)
  self.assertLessEqual(engine.status()['retained_samples'],128)
  for source in ('swim_tfms','flights_js'):
   excluded=MotionEngine(source);excluded.observe([dict(hex='a',lat=42,lon=-77)])
   self.assertEqual(excluded.status()['retained_pattern_samples'],0)

 def test_sfdps_report_cadence_patterns_and_ground_reset(self):
  now=[BASE];engine=MotionEngine('swim_sfdps',clock=lambda:now[0])
  def publish(t,ground=False):
   p=sample(t,10000*math.cos(math.radians(t)),10000*math.sin(math.radians(t)))
   now[0]=p['t'];engine.observe([dict(hex='s',lat=p['lat'],lon=p['lon'],alt_baro='ground' if ground else 10000,gs=340)],now[0],now[0],{'s':{'position_time':p['t']}})
  for t in range(0,793,12):publish(t)
  state=engine.snapshot(now=now[0])['aircraft']['s'];self.assertEqual(state['patterns'][0]['name'],'repeated_orbit')
  summary=engine.periodic_summary(now=now[0],monotonic_now=100)
  self.assertEqual(summary['patterns']['repeated_orbit:established'],1)
  publish(804,True);state=engine.snapshot(now=now[0],include_events=True)['aircraft']['s']
  self.assertEqual(state['patterns'],[]);self.assertEqual(state['pattern_history_samples'],1)
  self.assertTrue(any(p['ended_reason']=='ground_transition' for p in state['completed_patterns']))
 def test_short_turns_and_reversal_expiry(self):
  self.assertEqual(detect(orbit(.15)),[])
  data=orbit(.5);last=data[-1]
  for dt in range(10,201,10):data.append(sample(last['t']-BASE+dt,-10000,-170*dt))
  self.assertEqual(detect(data),[])

 def test_engine_reset_stale_and_bounded_history(self):
  now=[BASE];engine=MotionEngine('sbs_30003',clock=lambda:now[0])
  data=orbit()
  for s in data:
   now[0]=s['t'];engine.observe([dict(hex='abc123',lat=s['lat'],lon=s['lon'],alt_baro=10000)],now[0],now[0],{'abc123':{'position_time':s['t']}})
  state=engine.snapshot(now=now[0])['aircraft']['abc123'];self.assertEqual(state['patterns'][0]['name'],'repeated_orbit')
  self.assertEqual(engine.snapshot(now=now[0]+16)['aircraft']['abc123']['patterns'],[])
  last=data[-1];now[0]+=60;engine.observe([dict(hex='abc123',lat=last['lat']+.01,lon=last['lon'],alt_baro=10000)],now[0],now[0],{'abc123':{'position_time':now[0]}})
  state=engine.snapshot(now=now[0],include_events=True)['aircraft']['abc123'];self.assertEqual(state['patterns'],[])
  self.assertTrue(any(p['ended_reason']=='observation_gap' for p in state['completed_patterns']))
  self.assertLessEqual(state['pattern_history_samples'],LIMITS['max_samples'])
