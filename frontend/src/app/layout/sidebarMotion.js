const SHAPES = {"mark":"M 345,463 V 326 C 345,270 387,225 439,225 C 475,225 507,242 527,267 C 548,242 580,225 616,225 C 670,225 708,269 708,326 V 463 H 660 V 326 C 660,296 643,272 615,272 C 581,272 550,296 550,330 V 463 H 502 V 330 C 502,296 473,272 440,272 C 412,272 393,296 393,326 V 463 Z","letters":["M880.198 411.98 919.647 418.604Q912.039 440.309 895.626 451.654Q879.212 463 854.557 463Q815.531 463 796.793 437.49Q782 417.054 782 385.906Q782 348.698 801.442 327.628Q820.885 306.557 850.612 306.557Q884.002 306.557 903.304 328.614Q922.606 350.671 921.76 396.195H822.576Q822.998 413.812 832.156 423.607Q841.314 433.403 854.98 433.403Q864.278 433.403 870.618 428.329Q876.958 423.255 880.198 411.98ZM882.453 371.953Q882.03 354.758 873.577 345.809Q865.124 336.859 853.007 336.859Q840.046 336.859 831.592 346.302Q823.139 355.745 823.28 371.953Z","M953.601 309.94H990.091V330.376Q1009.674 306.557 1036.724 306.557Q1051.095 306.557 1061.661 312.477Q1072.228 318.396 1078.99 330.376Q1088.853 318.396 1100.264 312.477Q1111.676 306.557 1124.638 306.557Q1141.122 306.557 1152.534 313.252Q1163.945 319.946 1169.581 332.913Q1173.667 342.497 1173.667 363.919V459.617H1134.077V374.067Q1134.077 351.799 1129.992 345.315Q1124.497 336.859 1113.085 336.859Q1104.773 336.859 1097.447 341.933Q1090.121 347.007 1086.88 356.802Q1083.64 366.597 1083.64 387.738V459.617H1044.05V377.591Q1044.05 355.745 1041.937 349.403Q1039.824 343.06 1035.386 339.96Q1030.948 336.859 1023.34 336.859Q1014.182 336.859 1006.856 341.792Q999.53 346.725 996.36 356.027Q993.19 365.329 993.19 386.893V459.617H953.601Z","M1206.493 382.664Q1206.493 362.933 1216.215 344.47Q1225.936 326.007 1243.758 316.282Q1261.58 306.557 1283.559 306.557Q1317.513 306.557 1339.209 328.614Q1360.906 350.671 1360.906 384.356Q1360.906 418.322 1338.998 440.661Q1317.09 463 1283.841 463Q1263.271 463 1244.603 453.698Q1225.936 444.396 1216.215 426.426Q1206.493 408.456 1206.493 382.664ZM1247.069 384.779Q1247.069 407.047 1257.635 418.886Q1268.202 430.725 1283.7 430.725Q1299.197 430.725 1309.693 418.886Q1320.189 407.047 1320.189 384.497Q1320.189 362.51 1309.693 350.671Q1299.197 338.832 1283.7 338.832Q1268.202 338.832 1257.635 350.671Q1247.069 362.51 1247.069 384.779Z","M1432.336 459.617H1392.746V309.94H1429.518V331.221Q1438.957 316.141 1446.495 311.349Q1454.032 306.557 1463.613 306.557Q1477.138 306.557 1489.677 314.027L1477.42 348.557Q1467.417 342.074 1458.823 342.074Q1450.51 342.074 1444.734 346.654Q1438.957 351.235 1435.647 363.215Q1432.336 375.195 1432.336 413.389Z","M1509.26 289.644V253H1548.85V289.644ZM1509.26 459.617V309.94H1548.85V459.617Z","M1621.547 355.604 1585.621 349.121Q1591.679 327.416 1606.472 316.987Q1621.266 306.557 1650.429 306.557Q1676.916 306.557 1689.878 312.829Q1702.839 319.101 1708.123 328.755Q1713.406 338.409 1713.406 364.201L1712.983 410.43Q1712.983 430.161 1714.885 439.534Q1716.787 448.906 1722 459.617H1682.833Q1681.284 455.671 1679.029 447.919Q1678.043 444.396 1677.621 443.268Q1667.477 453.134 1655.924 458.067Q1644.371 463 1631.269 463Q1608.163 463 1594.849 450.456Q1581.535 437.913 1581.535 418.745Q1581.535 406.06 1587.594 396.124Q1593.652 386.188 1604.57 380.903Q1615.489 375.617 1636.059 371.671Q1663.814 366.456 1674.521 361.946V358Q1674.521 346.584 1668.885 341.721Q1663.25 336.859 1647.612 336.859Q1637.045 336.859 1631.128 341.017Q1625.21 345.174 1621.547 355.604ZM1674.521 387.738Q1666.913 390.275 1650.429 393.799Q1633.945 397.322 1628.874 400.705Q1621.125 406.201 1621.125 414.658Q1621.125 422.973 1627.324 429.034Q1633.523 435.094 1643.103 435.094Q1653.811 435.094 1663.532 428.047Q1670.717 422.691 1672.971 414.94Q1674.521 409.866 1674.521 395.631Z"]};
const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
const phase = (p, a, b) => clamp((p - a) / (b - a));
const smooth = x => x * x * (3 - 2 * x);
const out = x => 1 - (1 - x) ** 4;
const fmt = x => Number(x.toFixed(3));
const cubic = (a, b, c, d, t) => (1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t*t*c + t**3*d;

function markup(uid) {
  const glyphs = SHAPES.letters.map((d, i) => `<g data-letter="${i}"><path class="letter-outline" d="${d}" pathLength="1"/><path class="letter-fill" d="${d}"/></g>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1580 600" role="img" aria-labelledby="${uid}">
    <title id="${uid}">Memoria</title>
    <g transform="translate(-220 -20)">
      <g data-mark transform="translate(0 0)">
        <path data-band d="M310 340C310 76 743 76 743 340" fill="none" stroke="var(--memoria-ink, #fff)" stroke-width="20" stroke-linecap="round"/>
        <g fill="var(--memoria-ink, #fff)"><rect x="273" y="312" width="66" height="110" rx="26"/><rect x="714" y="312" width="66" height="110" rx="26"/>
        <path data-m d="${SHAPES.mark}"/></g>
        <path data-boom d="M743 390C749 464 692 499 621 499" fill="none" stroke="var(--memoria-ink, #fff)" stroke-width="12" stroke-linecap="round"/>
      </g>
      <g data-word transform="translate(24 0)">${glyphs}</g>
      <path data-thread fill="none" stroke="var(--memoria-accent, #df482f)" stroke-width="7" stroke-linecap="round"/>
      <path data-trail fill="none" stroke="var(--memoria-accent, #df482f)" stroke-width="11" stroke-linecap="round" opacity=".35"/>
    </g>
  </svg>`;
}

function draw(svg, p) {
  const starts = [.20, .28, .36, .44, .52, .60];
  const xs = [782, 954, 1206, 1393, 1509, 1582];
  svg.querySelectorAll('[data-letter]').forEach((g, i) => {
    const q = phase(p, starts[i], starts[i] + .31);
    const e = out(q);
    const scaleX = .12 + .88 * e;
    const scaleY = .64 + .36 * e;
    const dx = -54*(1-e), dy = 46*(1-e);
    g.setAttribute('transform', `translate(${fmt(xs[i]+dx)} ${fmt(463+dy)}) skewX(${fmt(-12*(1-e))}) scale(${fmt(scaleX)} ${fmt(scaleY)}) translate(${-xs[i]} -463)`);
    const line = g.querySelector('.letter-outline');
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', 'var(--memoria-ink, #fff)');
    line.setAttribute('stroke-width', '3.5');
    line.setAttribute('stroke-dasharray', '1');
    line.setAttribute('stroke-dashoffset', fmt(1-out(phase(q, 0, .65))));
    line.setAttribute('opacity', fmt(smooth(phase(q, 0, .12))*(1-smooth(phase(q, .50, .94)))));
    const fill = g.querySelector('.letter-fill');
    fill.setAttribute('fill', 'var(--memoria-ink, #fff)');
    fill.setAttribute('opacity', fmt(smooth(phase(q, .27, .87))));
  });

  const t = smooth(phase(p, .08, .91));
  const segments = [
    {end:.43, p:[605,499,755,574,1010,560,1175,457]},
    {end:.64, p:[1175,457,1242,415,1370,409,1347,347]},
    {end:.82, p:[1347,347,1324,285,1212,308,1253,371]},
    {end:1, p:[1253,371,1294,434,1476,276,1552,270]}
  ];
  function threadPoint(u) {
    let start=0;
    for(const s of segments){
      if(u<=s.end){const v=(u-start)/(s.end-start),a=s.p;return [cubic(a[0],a[2],a[4],a[6],v),cubic(a[1],a[3],a[5],a[7],v)];}
      start=s.end;
    }
    return [1552,270];
  }
  const points = [];
  const tail = Math.max(0, t - .43);
  for (let j = 0; j <= 32; j++) {
    const u = tail + (t-tail)*j/32;
    const [x,y]=threadPoint(u);
    points.push(`${j ? 'L' : 'M'}${fmt(x)} ${fmt(y)}`);
  }
  const threadOpacity = smooth(phase(p,.08,.16))*(1-smooth(phase(p,.73,.92)));
  const thread = svg.querySelector('[data-thread]');
  thread.setAttribute('d', points.join(' '));
  thread.setAttribute('opacity', fmt(threadOpacity * .8));
  const trail = svg.querySelector('[data-trail]');
  trail.setAttribute('d', points.slice(23).map((point, i) => i === 0 ? point.replace('L','M') : point).join(' '));
  trail.setAttribute('opacity', fmt(threadOpacity * .28));
  const [nx,ny]=threadPoint(t);
  return [fmt(nx),fmt(ny)];
}


export function createSidebarMotion(sidebar, host, id) {
  const shell = sidebar.closest('.app-layout');
  host.innerHTML = markup(id);
  const svg = host.querySelector('svg');
  const drawing = svg.querySelector('[data-mark]').parentElement;
  const ns = 'http://www.w3.org/2000/svg';
  const orange = '#e4482e';
  const mix = (a,b,t) => a+(b-a)*t;
  const set = (n,attrs) => Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));
  function element(tag, attrs, parent) {
    const node = document.createElementNS(ns,tag);
    set(node,attrs); parent.appendChild(node); return node;
  }
  const defs = element('defs',{},svg);
  const blur = element('filter',{id:'arrival',x:'-100%',y:'-100%',width:'300%',height:'300%'},defs);
  element('feGaussianBlur',{stdDeviation:9},blur);
  const glow = element('rect',{fill:orange,filter:'url(#arrival)',opacity:0},drawing);
  const tip = element('rect',{fill:orange},drawing);
  const iPaths = [...svg.querySelectorAll('[data-letter="4"] path')];
  const originalI = iPaths[0].getAttribute('d');
  const stemOnly = 'M1509.26 459.617V309.94H1548.85V459.617Z';

  const poses = [
    [   0, 1.00, 1.00,   0,  0, 0.00],
    [  90, 1.28, 0.68,   6, -5, 0.10],
    [ 170, 0.74, 1.45, -17,  4, 0.35],
    [ 270, 1.14, 1.10, -34,  3, 0.65],
    [ 360, 1.32, 0.70,   5, -3, 0.22],
    [ 500, 1.00, 1.00,   0,  0, 0.00]
  ];
  function beatAt(ms) {
    const t=ms-2200;
    if(t<=0 || t>=500) return [1,1,0,0,0];
    const i=poses.findIndex((pose,index)=>index<poses.length-1 && t>=pose[0] && t<poses[index+1][0]);
    const a=poses[i], b=poses[i+1], before=poses[Math.max(0,i-1)], after=poses[Math.min(poses.length-1,i+2)];
    const span=b[0]-a[0], u=(t-a[0])/span;
    const h00=2*u**3-3*u**2+1, h10=u**3-2*u**2+u;
    const h01=-2*u**3+3*u**2, h11=u**3-u**2;
    return a.slice(1).map((v,j)=>{
      const c=j+1;
      const m0=i===0?0:.8*(b[c]-before[c])/(b[0]-before[0]);
      const m1=i+1===poses.length-1?0:.8*(after[c]-a[c])/(after[0]-a[0]);
      return h00*v+h10*span*m0+h01*b[c]+h11*span*m1;
    });
  }
  function render(ms) {
    const p=clamp((ms-650)/1500);
    const [nx,ny]=draw(svg,p);
    const departure=smooth(phase(p,.08,.22));
    const landing=smooth(phase(p,.75,.91));
    const x=nx + 1.055*landing;
    const y=ny - .5*(1-departure) + 1.322*landing;
    const [stretchX,stretchY,lift,tilt,warmth]=beatAt(ms);
    const width=mix(mix(54,24,departure),39.59,landing)*stretchX;
    const height=mix(mix(29,24,departure),36.644,landing)*stretchY;
    const centerY=y+lift;
    const flex=Math.max(Math.abs(stretchX-1),Math.abs(stretchY-1));
    const radius=mix(mix(14,12,departure),0,landing)+Math.min(6,flex*18);
    const fill=`rgb(${Math.round(mix(228,249,warmth))},${Math.round(mix(72,111,warmth))},${Math.round(mix(46,48,warmth))})`;
    set(tip,{x:x-width/2,y:centerY-height/2,width,height,rx:radius,fill,transform:`rotate(${tilt} ${x} ${centerY})`});
    set(glow,{x:x-width/2-4,y:centerY-height/2-4,width:width+8,height:height+8,rx:8,opacity:.2*Math.max(0,warmth)});
    iPaths.forEach(path=>path.setAttribute('d',p>=.91?stemOnly:originalI));
  }

  const END=2050, SPEED=2.5;
  const compactWidth=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width')) || 88;
  const expandedWidth=parseFloat(getComputedStyle(sidebar).getPropertyValue('--sidebar-expanded-width')) || 288;
  const reduced=typeof matchMedia==='function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
  let time=0,target=0,frame=0,previous=0;
  function paint() {
    render(650+time);
    const progress=Math.min(1,time/1500);
    const expansion=smooth(progress);
    const width = compactWidth+(expandedWidth-compactWidth)*expansion;
    sidebar.style.setProperty('--sidebar-width', `${width}px`);
    shell?.style.setProperty('--sidebar-overlap', `${width-compactWidth}px`);
    sidebar.style.setProperty('--label-opacity',smooth(Math.max(0,(progress-.3)/.7)));
    sidebar.style.setProperty('--shadow-opacity',.16*expansion);
  }
  function tick(now) {
    const dt=Math.min(32,now-previous); previous=now;
    const direction=Math.sign(target-time);
    time=direction>0 ? Math.min(target,time+SPEED*dt) : Math.max(target,time-SPEED*dt);
    paint();
    if(time===target) frame=0;
    else frame=requestAnimationFrame(tick);
  }
  function setExpanded(expanded) {
    target=expanded ? END : 0;
    if(!expanded && time>1500) time=1500;
    if(reduced?.matches || typeof requestAnimationFrame!=='function') {
      if(frame) cancelAnimationFrame(frame);
      frame=0; time=target; paint();
    } else if(!frame && time!==target) {
      previous=performance.now(); frame=requestAnimationFrame(tick);
    }
  }
  const motionChanged=()=>setExpanded(target!==0);
  reduced?.addEventListener('change',motionChanged);
  paint();
  return {
    setExpanded,
    isCollapsed: () => time === 0,
    destroy() {
      if(frame) cancelAnimationFrame(frame);
      reduced?.removeEventListener('change',motionChanged);
      shell?.style.removeProperty('--sidebar-overlap');
      host.replaceChildren();
    },
  };
}
