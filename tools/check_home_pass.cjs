const fs=require('fs'),vm=require('vm'),assert=require('assert');
const text=fs.readFileSync(process.argv[2],'utf8');
const begin=text.indexOf('function currentMotionState('),end=text.indexOf('function motionLabels(',begin);
const c=vm.createContext({motionFreshSeconds:15,motionStates:{a:{quality:'supported',position_age_seconds:0,fetched_at:Date.now()/1000,home_pass:{predicted_at:Date.now()/1000,slant_nm:2.1,horizontal_nm:1,vertical_ft:10000,seconds:60,altitude_basis:'alt_baro',quality:'constant_velocity_baseline'}}},esc:String});
vm.runInContext(text.slice(begin,end),c);assert(vm.runInContext("homePassHtml('a')",c).includes('2.10 NM slant in 60 s'));
vm.runInContext("motionStates.a.home_pass.predicted_at-=60",c);assert.equal(vm.runInContext("homePassHtml('a')",c),'');
assert(text.includes("if(flags.homePass)classes.push('home-pass')"));assert(text.includes('id="home-pass-highlight"'));assert(text.includes("document.getElementById('home-pass-highlight').addEventListener('change',applyMotionView)"));
console.log('PASS home-pass popup measurements, expiry, halo class and control binding');
