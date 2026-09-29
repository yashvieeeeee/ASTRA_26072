import { useEffect, useRef, useState } from "react";

type Mode = "Overview" | "Storms" | "Nowcast" | "Risk" | "Warnings" | "Infrastructure" | "Data" | "Audit";
type Layer = "Probability" | "Lightning" | "Tracks" | "Risk fields" | "Infrastructure";
type Storm = {
  id: string;
  x: number;
  y: number;
  risk: "SEVERE" | "HIGH" | "MODERATE";
  probability: number;
  lightning: number;
  confidence: number;
  speed: number;
  eta: number;
  place: string;
};

const storms: Storm[] = [
  { id: "AST-024", x: 35, y: 54, risk: "HIGH", probability: 87, lightning: 74, confidence: 91, speed: 42, eta: 18, place: "Nashik · Dhule · Jalgaon" },
  { id: "AST-019", x: 39, y: 27, risk: "SEVERE", probability: 93, lightning: 82, confidence: 88, speed: 36, eta: 12, place: "Hisar · Rohtak · Jhajjar" },
  { id: "AST-031", x: 75, y: 36, risk: "HIGH", probability: 81, lightning: 69, confidence: 86, speed: 48, eta: 24, place: "Guwahati · Nagaon" },
  { id: "AST-017", x: 49, y: 48, risk: "MODERATE", probability: 68, lightning: 42, confidence: 79, speed: 28, eta: 31, place: "Bhopal · Raisen" },
  { id: "AST-028", x: 44, y: 76, risk: "HIGH", probability: 84, lightning: 78, confidence: 89, speed: 34, eta: 21, place: "Bengaluru Rural · Kolar" },
  { id: "AST-033", x: 69, y: 55, risk: "MODERATE", probability: 71, lightning: 57, confidence: 83, speed: 31, eta: 27, place: "Kolkata · Howrah" },
];

const nav: { mode: Mode; icon: string }[] = [
  { mode: "Overview", icon: "orbit" },
  { mode: "Storms", icon: "storm" },
  { mode: "Nowcast", icon: "timeline" },
  { mode: "Risk", icon: "risk" },
  { mode: "Warnings", icon: "warning" },
  { mode: "Infrastructure", icon: "facility" },
  { mode: "Data", icon: "data" },
  { mode: "Audit", icon: "audit" },
];

function Icon({ name, size = 19 }: { name: string; size?: number }) {
  const p: Record<string, React.ReactNode> = {
    orbit: <><circle cx="12" cy="12" r="3"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(45 12 12)"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(-45 12 12)"/></>,
    storm: <><path d="M18.5 17H7a4 4 0 1 1 .8-7.9A6 6 0 0 1 19 11a3 3 0 0 1-.5 6Z"/><path d="m13 11-2 4h3l-2 6"/></>,
    timeline: <><path d="M3 12h18"/><circle cx="7" cy="12" r="2"/><circle cx="17" cy="12" r="2"/></>,
    risk: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="M12 8v5M12 17h.01"/></>,
    warning: <><path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5M12 18h.01"/></>,
    facility: <><path d="M4 21V6h10v15M14 10h6v11M8 10h2M8 14h2M8 18h2M2 21h20"/></>,
    data: <><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/></>,
    audit: <><path d="M6 3h12v18H6zM9 8h6M9 12h6M9 16h4"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
    layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5M3 17l9 5 9-5"/></>,
    play: <path d="m8 5 11 7-11 7Z"/>,
    pause: <><path d="M8 5v14M16 5v14"/></>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    edit: <><path d="m4 20 4-.8L19 8.2 15.8 5 4.8 16Z"/><path d="m14 6 3 3"/></>,
    lightning: <path d="m13 2-7 12h6l-1 8 7-12h-6Z"/>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    target: <><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
    hospital: <><path d="M5 3h14v18H5zM9 8h6M12 5v6M8 21v-5h8v5"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.55" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{p[name]}</svg>;
}

function Action({ children, onClick, primary, danger, className = "" }: { children: React.ReactNode; onClick?: () => void; primary?: boolean; danger?: boolean; className?: string }) {
  return <div role="button" tabIndex={0} className={`action ${primary ? "primary" : ""} ${danger ? "danger" : ""} ${className}`} onClick={onClick} onKeyDown={(e) => e.key === "Enter" && onClick?.()}>{children}</div>;
}

function Mark({ children, tone = "violet" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`mark ${tone}`}>{children}</span>;
}

const indiaPath = "M168 25l24 16 19 25 20 12 19 3 18 24-14 17 5 18-14 16-5 27-12 19-10 26-11 21-11 31-11 26-12 34-12 25-12-28-13-23-12-31-14-27-13-23-9-25-15-18-7-23-16-16 6-22 16-7 6-18 12-12-2-18 16-12 11-21 20-5 13-19 21-6 13-18Zm100 81 20-12 26 10 22-7 20 14-20 15-26-7-17 14-22-7Z";

function AtmosphericMap({
  selected,
  setSelected,
  horizon,
  layers,
  mode,
}: {
  selected: Storm | null;
  setSelected: (s: Storm) => void;
  horizon: number;
  layers: Set<Layer>;
  mode: Mode;
}) {
  return <div className={`atmosphere-map ${selected ? "has-selection" : ""} mode-${mode.toLowerCase()}`}>
    <div className="aurora aurora-a"></div><div className="aurora aurora-b"></div>
    <div className="cloud-field cloud-a"></div><div className="cloud-field cloud-b"></div>
    <div className="geo-grid"></div>
    <svg className="india-canvas" viewBox="0 0 400 420" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="terrain" x1="0" y1="0" x2="1" y2="1"><stop stopColor="var(--map-high)"/><stop offset=".52" stopColor="var(--map-mid)"/><stop offset="1" stopColor="var(--map-low)"/></linearGradient>
        <radialGradient id="fieldSevere"><stop stopColor="var(--white-hot)" stopOpacity=".92"/><stop offset=".16" stopColor="var(--critical)" stopOpacity=".86"/><stop offset=".43" stopColor="var(--magenta)" stopOpacity=".52"/><stop offset=".74" stopColor="var(--violet)" stopOpacity=".2"/><stop offset="1" stopColor="var(--violet)" stopOpacity="0"/></radialGradient>
        <radialGradient id="fieldHigh"><stop stopColor="var(--gold)" stopOpacity=".84"/><stop offset=".27" stopColor="var(--magenta)" stopOpacity=".63"/><stop offset=".62" stopColor="var(--violet)" stopOpacity=".28"/><stop offset="1" stopColor="var(--violet)" stopOpacity="0"/></radialGradient>
        <radialGradient id="fieldModerate"><stop stopColor="var(--cyan)" stopOpacity=".68"/><stop offset=".42" stopColor="var(--violet)" stopOpacity=".38"/><stop offset="1" stopColor="var(--violet)" stopOpacity="0"/></radialGradient>
        <filter id="stormGlow"><feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        <filter id="softGlow"><feGaussianBlur stdDeviation="12"/></filter>
        <clipPath id="indiaClip"><path d={indiaPath}/></clipPath>
      </defs>
      <path d={indiaPath} fill="url(#terrain)" stroke="var(--coast)" strokeWidth="1.2"/>
      <g clipPath="url(#indiaClip)" opacity=".26" fill="none" stroke="var(--terrain-line)" strokeWidth=".7">
        <path d="M46 171q80-52 192-12M59 192q93-44 179-9M79 233q67-29 143-8M99 276q52-14 103-2M120 319q31-4 60 5"/>
        <path d="M91 94q54 28 116-26M67 145q85 33 182-23M112 65q10 52 42 68M211 67q-29 45-57 66"/>
      </g>
      <g className="state-lines" fill="none" stroke="var(--state-line)" strokeWidth=".65">
        <path d="M83 116l69 16 57-66M67 146l78 25 99-18M61 190l90 10 89-19M82 232l72-3 64-4M105 278l66-11 36-18M130 337l45-24 11-10M145 171l-2 190M110 65l42 67M210 66l-58 66M245 153l-94 47M207 246l-53-17M286 94l24 26"/>
      </g>
      <g className="city-labels">
        {[[132,91,"DELHI"],[98,186,"AHMEDABAD"],[105,237,"MUMBAI"],[174,206,"NAGPUR"],[264,214,"KOLKATA"],[154,322,"BENGALURU"],[168,372,"CHENNAI"],[149,252,"HYDERABAD"],[302,112,"GUWAHATI"]].map(([x,y,n])=><g key={n as string}><circle cx={x as number} cy={y as number} r="1.5"/><text x={(x as number)+5} y={(y as number)+2}>{n}</text></g>)}
      </g>
      {layers.has("Risk fields") && <g className="risk-wash"><ellipse cx="126" cy="220" rx="66" ry="42"/><ellipse cx="297" cy="124" rx="47" ry="29"/></g>}
      {storms.map((s, index) => {
        const progress = selected?.id === s.id ? horizon / 60 : 0;
        const cx = s.x * 3.35 + 8 + progress * 24;
        const cy = s.y * 4.05 - 5 - progress * 17;
        const baseX = s.x * 3.35 + 8;
        const baseY = s.y * 4.05 - 5;
        const gradient = s.risk === "SEVERE" ? "url(#fieldSevere)" : s.risk === "HIGH" ? "url(#fieldHigh)" : "url(#fieldModerate)";
        return <g key={s.id} className={`storm-system ${selected?.id === s.id ? "selected" : ""}`} role="button" tabIndex={0} onClick={() => setSelected(s)}>
          {layers.has("Probability") && <><ellipse cx={cx} cy={cy} rx={s.risk === "SEVERE" ? 45 + progress * 8 : 35 + progress * 7} ry={s.risk === "SEVERE" ? 34 + progress * 6 : 29 + progress * 6} fill={gradient} className="probability-field"/><ellipse cx={cx-7} cy={cy+7} rx="20" ry="13" fill={gradient} opacity=".66"/></>}
          {layers.has("Lightning") && s.lightning > 65 && <g className={`lightning-burst delay-${index % 3}`} transform={`translate(${cx-4} ${cy-11})`}><path d="m3 0-5 8h4l-2 7 7-10H3Z"/></g>}
          {selected?.id === s.id && layers.has("Tracks") && <g className="trajectory">
            <path className="past-track" d={`M${baseX-45} ${baseY+32} Q${baseX-22} ${baseY+16} ${baseX} ${baseY}`}/>
            <path className="uncertainty" d={`M${baseX} ${baseY} Q${baseX+48} ${baseY-22} ${baseX+85+horizon*.28} ${baseY-65-horizon*.08} L${baseX+81+horizon*.28} ${baseY-40+horizon*.15} Q${baseX+40} ${baseY-12} ${baseX} ${baseY}Z`}/>
            <path className="forecast-track" d={`M${baseX} ${baseY} Q${baseX+48} ${baseY-22} ${baseX+83+horizon*.28} ${baseY-52}`}/>
            {[.25,.52,.78,1].map((n)=><circle key={n} cx={baseX+(83+horizon*.28)*n} cy={baseY-52*n+(n-.5)*8} r="2.5"/>)}
            <g className="vector-label" transform={`translate(${baseX+48} ${baseY-48})`}><rect x="-4" y="-11" width="70" height="20" rx="3"/><text x="3" y="2">{s.speed} KM/H · NE</text></g>
          </g>}
          <circle cx={cx} cy={cy} r={selected?.id === s.id ? 10 : 6} className="centroid-halo"/>
          <circle cx={cx} cy={cy} r="2.6" className="centroid"/>
          <g className="storm-id" transform={`translate(${cx+10} ${cy-14})`}><text>{s.id}</text></g>
          <g className="storm-tooltip" transform={`translate(${cx+12} ${cy+8})`}><rect width="95" height="50" rx="4"/><text x="8" y="14" className={`risk-${s.risk.toLowerCase()}`}>{s.risk}</text><text x="8" y="29">{s.probability}% PROBABILITY</text><text x="8" y="42">NE → {s.speed} KM/H</text></g>
        </g>;
      })}
      {layers.has("Infrastructure") && <g className="facilities">
        {[[119,216,"H"],[135,222,"R"],[155,278,"+"],[260,218,"H"],[133,105,"A"],[303,119,"E"]].map(([x,y,t],i)=><g key={i} transform={`translate(${x} ${y})`}><circle r="8"/><text textAnchor="middle" y="2.5">{t}</text>{selected && i < 2 && <path d={`M0 0 Q${-12-i*10} ${-18-i*4} ${-24-i*16} ${-28-i*10}`} className="facility-link"/>}</g>)}
      </g>}
    </svg>
    <div className="map-domain"><span>38°N</span><span>INDIA · 6–38°N / 68–98°E</span><span>6°N</span></div>
    <div className="intensity-key"><span>ATMOSPHERIC INTENSITY</span><i></i><div><b>LOW</b><b>MODERATE</b><b>HIGH</b><b>SEVERE</b></div></div>
    <div className="map-credit">IMD ADMIN BOUNDARIES · 0.25° GRID · ASTRA AI COMPOSITE</div>
  </div>;
}

function NavRail({ mode, setMode }: { mode: Mode; setMode: (m: Mode) => void }) {
  return <aside className="nav-rail">
    <div className="astra-sigil"><i></i><i></i><i></i><span></span></div>
    <div className="nav-items">{nav.map((item)=><div key={item.mode} role="button" tabIndex={0} className={`nav-item ${mode === item.mode ? "active" : ""}`} onClick={()=>setMode(item.mode)}><Icon name={item.icon}/><span>{item.mode}</span>{item.mode === "Warnings" && <b>5</b>}</div>)}</div>
    <div className="rail-status"><span></span><em>Operational</em></div>
  </aside>;
}

function TopHud({ setMode }: { setMode: (m: Mode) => void }) {
  return <div className="top-hud">
    <div className="identity"><div>ASTRA</div><span>AI STORM INTELLIGENCE</span></div>
    <div className="live-context"><strong>PAN-INDIA</strong><span><i></i> LIVE</span><b>08:42:18 IST</b></div>
    <div className="top-actions"><div role="button" tabIndex={0}><Icon name="search"/></div><div role="button" tabIndex={0} onClick={()=>setMode("Warnings")}><Icon name="bell"/><i></i></div><div className="avatar">RK</div></div>
  </div>;
}

function Telemetry({ degraded }: { degraded: boolean }) {
  return <div className="telemetry">
    <div><strong>24</strong><span>ACTIVE STORMS</span></div><i></i>
    <div className="severe"><strong>05</strong><span>SEVERE</span></div><i></i>
    <div><strong>17</strong><span>LIGHTNING CELLS</span></div>
    {degraded && <div className="confidence-alert"><Icon name="info" size={14}/><span>MODEL CONFIDENCE REDUCED</span></div>}
  </div>;
}

function LayerControl({ layers, toggle }: { layers: Set<Layer>; toggle: (l: Layer) => void }) {
  const [open,setOpen]=useState(false);
  const items: { name: Layer; color: string }[] = [
    {name:"Probability",color:"violet"},{name:"Lightning",color:"gold"},{name:"Tracks",color:"cyan"},{name:"Risk fields",color:"magenta"},{name:"Infrastructure",color:"mint"}
  ];
  return <div className={`layer-control ${open ? "open" : ""}`}>
    <div className="layer-trigger" role="button" tabIndex={0} onClick={()=>setOpen(!open)}><Icon name="layers"/><span>LAYERS</span><b>{layers.size}</b></div>
    {open && <div className="layer-menu"><div className="micro-label">ATMOSPHERIC LAYERS</div>{items.map(({name,color})=><div key={name} className="layer-row" role="checkbox" aria-checked={layers.has(name)} tabIndex={0} onClick={()=>toggle(name)}><i className={layers.has(name) ? `on ${color}` : ""}></i><span>{name}</span><em>{layers.has(name) ? "VISIBLE" : "HIDDEN"}</em></div>)}</div>}
  </div>;
}

function DataHealth({ degraded, setDegraded }: { degraded: boolean; setDegraded: (d: boolean) => void }) {
  const [open,setOpen]=useState(false);
  return <div className={`data-health ${open ? "open" : ""}`}>
    <div className="data-trigger" role="button" tabIndex={0} onClick={()=>setOpen(!open)}><span>DATA</span><div><i className="live"></i><i className="live"></i><i className={degraded?"degraded":"live"}></i><i className="live"></i><i className="synthetic"></i></div><Icon name="chevron" size={13}/></div>
    {open && <div className="data-panel"><div className="data-title"><span>INPUT SOURCE HEALTH</span><b>08:42 IST</b></div>
      {[["Radar","LIVE","1m"],["Satellite","LIVE","4m"],["Ground Stations",degraded?"DEGRADED":"LIVE",degraded?"30m":"2m"],["NWP","LIVE","12m"],["Lightning","SYNTHETIC","Now"]].map(([name,status,age])=><div className="source-line" key={name} role={name==="Ground Stations"?"button":undefined} tabIndex={name==="Ground Stations"?0:undefined} onClick={()=>name==="Ground Stations"&&setDegraded(!degraded)}><i className={status.toLowerCase()}></i><span>{name}</span><b className={status.toLowerCase()}>{status}</b><em>{age}</em></div>)}
      <div className="data-foot">Select Ground Stations to demonstrate live degradation response.</div>
    </div>}
  </div>;
}

function IntelligencePanel({ storm, close, degraded, openImpact }: { storm: Storm; close: () => void; degraded: boolean; openImpact: () => void }) {
  const confidence = degraded ? storm.confidence - 7 : storm.confidence;
  return <div className="intelligence-panel">
    <div className="panel-axis"></div>
    <div className="intelligence-head"><div><span>STORM INTELLIGENCE</span><strong>{storm.id}</strong></div><Action onClick={close}><Icon name="close"/></Action></div>
    <div className="risk-line"><Mark tone={storm.risk.toLowerCase()}>{storm.risk} RISK</Mark><span>INTENSIFYING <b>↗ 18%</b></span></div>
    <div className="hero-probability"><strong>{storm.probability}<sup>%</sup></strong><span>STORM<br/>PROBABILITY</span></div>
    <div className="instrument-grid">
      <div><span>CONFIDENCE</span><strong className={degraded?"reduced":""}>{confidence}%</strong><i><b style={{width:`${confidence}%`}}></b></i></div>
      <div><span>LIGHTNING</span><strong>{storm.lightning}%</strong></div>
      <div><span>VELOCITY</span><strong>{storm.speed}<small> KM/H</small></strong></div>
      <div><span>EST. ARRIVAL</span><strong>{storm.eta}<small> MIN</small></strong></div>
    </div>
    <div className="affected-area"><span>PROJECTED IMPACT CORRIDOR</span><strong>{storm.place}</strong></div>
    {degraded && <div className="degraded-note"><Icon name="info" size={15}/><span>Confidence reduced due to delayed ground-station observations.</span></div>}
    <div className="panel-actions"><Action onClick={openImpact}>WHY THIS PREDICTION? <Icon name="arrow"/></Action><Action primary>OPEN STORM ANALYSIS <Icon name="arrow"/></Action></div>
  </div>;
}

function ImpactHud({ expanded, setExpanded, selected }: { expanded: boolean; setExpanded: (x: boolean) => void; selected: Storm | null }) {
  if (!selected) return null;
  return <div className={`impact-hud ${expanded ? "expanded" : ""}`} role="button" tabIndex={0} onClick={()=>!expanded&&setExpanded(true)}>
    <div className="impact-compact">
      <div className="impact-orbit"><svg viewBox="0 0 80 80"><circle cx="40" cy="40" r="34"/><circle className="score" cx="40" cy="40" r="34"/></svg><div><strong>82</strong><span>/100</span></div></div>
      <div><span>ASTRA IMPACT INDEX</span><strong>HIGH</strong><small>37 facilities exposed</small></div>
      <Icon name="chevron"/>
    </div>
    {expanded && <div className="impact-expanded" onClick={(e)=>e.stopPropagation()}>
      <div className="impact-head"><div><span>ASTRA IMPACT INDEX</span><strong>WHY THIS RISK MATTERS</strong></div><div role="button" tabIndex={0} onClick={()=>setExpanded(false)}><Icon name="close"/></div></div>
      <div className="impact-score-row"><div className="impact-orbit large"><svg viewBox="0 0 80 80"><circle cx="40" cy="40" r="34"/><circle className="score" cx="40" cy="40" r="34"/></svg><div><strong>82</strong><span>HIGH</span></div></div><div className="impact-metrics"><span>EXPOSURE <b>HIGH</b></span><span>CONFIDENCE <b>91%</b></span><span>ETA <b>18 MIN</b></span></div></div>
      <div className="contribution-title">RISK COMPOSITION</div>
      {[["Prediction Confidence",32,"violet"],["Infrastructure Exposure",41,"magenta"],["Intensity Trend",27,"gold"]].map(([n,v,c])=><div className="contribution" key={n}><span>{n}</span><i><b className={c} style={{width:`${v}%`}}></b></i><strong>{v}%</strong></div>)}
      <div className="attribution-title"><span>WHY THIS PREDICTION?</span><em>EXPLAINABLE AI OUTPUT</em></div>
      {[["Radar / Precipitation",31],["Satellite",24],["Lightning",19],["Ground Stations",11],["NWP",15]].map(([n,v])=><div className="attribution" key={n}><span>{n}</span><i><b style={{width:`${v}%`}}></b></i><strong>{v}%</strong></div>)}
      <div className="model-disclaimer">Attribution estimates each source's influence on this prediction. It is not a raw physical measurement.</div>
    </div>}
  </div>;
}

function ForecastTimeline({ horizon, setHorizon, playing, setPlaying, selected }: { horizon: number; setHorizon: (n: number) => void; playing: boolean; setPlaying: (p: boolean) => void; selected: Storm | null }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const validMinutes = 8 * 60 + 42 + horizon;
  const validTime = `${String(Math.floor(validMinutes / 60)).padStart(2, "0")}:${String(validMinutes % 60).padStart(2, "0")} IST`;
  const scrub = (e: React.PointerEvent<HTMLDivElement>) => {
    const box = trackRef.current?.getBoundingClientRect();
    if (!box) return;
    setHorizon(Math.max(0, Math.min(60, Math.round(((e.clientX - box.left) / box.width) * 60 / 10) * 10)));
  };
  return <div className={`forecast-timeline ${selected ? "active" : ""}`}>
    <Action className="play-control" onClick={()=>setPlaying(!playing)}><Icon name={playing?"pause":"play"}/><span>{playing?"PAUSE":"PLAY FORECAST"}</span></Action>
    <div className="timeline-main">
      <div className="timeline-meta"><span>PREDICTION HORIZON</span><strong>{horizon === 0 ? "NOW" : `+${horizon} MIN`}</strong><em>{selected ? `${selected.id} · ASTRA AI` : "SELECT A STORM TO INSPECT"}</em></div>
      <div className="timeline-track" ref={trackRef} onPointerDown={scrub}>
        <div className="timeline-fill" style={{width:`${horizon / 60 * 100}%`}}></div>
        {[0,10,20,30,40,50,60].map((n)=><div key={n} className={`tick ${horizon >= n ? "passed":""} ${horizon === n ? "current":""}`} style={{left:`${n/60*100}%`}} role="button" tabIndex={0} onClick={()=>setHorizon(n)}><i></i><span>{n===0?"NOW":n}</span></div>)}
        <div className="playhead" style={{left:`${horizon / 60 * 100}%`}}><i></i></div>
      </div>
    </div>
    <div className="forecast-reading"><span>VALID TIME</span><strong>{validTime}</strong></div>
  </div>;
}

type WarningState = "list" | "review" | "confirm" | "approved";
function WarningCenter({ state, setState, returnToMap }: { state: WarningState; setState: (s: WarningState) => void; returnToMap: () => void }) {
  const [message,setMessage]=useState("Severe thunderstorm activity is expected to affect Nashik, Dhule and Jalgaon districts within the next 20 minutes. Intense lightning, gusty winds and heavy rainfall are likely. Take precautionary action and monitor official IMD guidance.");
  if (state === "approved") return <div className="warning-overlay approval-state"><div className="approval-orbit"><div className="astra-sigil large"><i></i><i></i><i></i><span></span></div><div className="approval-check"><Icon name="check" size={30}/></div></div><Mark tone="mint">DECISION RECORDED</Mark><div className="approval-title">WARNING APPROVED</div><span className="approval-subtitle">Human authorization complete · Dispatch remains controlled by IMD procedure</span><div className="approval-details"><div><span>FORECASTER</span><strong>R. Kumar · Senior Forecaster</strong></div><div><span>TIME</span><strong>08:42 IST</strong></div><div><span>AUDIT ID</span><strong>ASTRA-W-02491</strong></div></div><Action primary onClick={returnToMap}>RETURN TO LIVE MAP <Icon name="arrow"/></Action></div>;
  if (state === "confirm") return <div className="warning-overlay"><div className="confirm-dialog"><div className="approval-check static"><Icon name="check" size={26}/></div><span className="micro-label">HUMAN AUTHORIZATION</span><div className="confirm-title">Approve warning?</div><p>ASTRA will record this decision in the audit trail. The warning is not automatically dispatched.</p><div><Action onClick={()=>setState("review")}>CANCEL</Action><Action primary onClick={()=>setState("approved")}>APPROVE WARNING <Icon name="check"/></Action></div></div></div>;
  const drafts = [
    ["AST-024","HIGH","Nashik · Dhule · Jalgaon","18 MIN","82","91%"],
    ["AST-019","SEVERE","Hisar · Rohtak · Jhajjar","12 MIN","91","88%"],
    ["AST-031","HIGH","Guwahati · Nagaon","24 MIN","76","86%"],
    ["AST-028","HIGH","Bengaluru Rural · Kolar","21 MIN","73","89%"],
  ];
  if (state === "review") return <div className="warning-workspace">
    <div className="warning-map-pane"><div className="warning-map-label"><span>STORM CONTEXT</span><strong>AST-024</strong></div><AtmosphericMap selected={storms[0]} setSelected={()=>{}} horizon={30} layers={new Set(["Probability","Lightning","Tracks","Infrastructure"])} mode="Warnings"/></div>
    <div className="warning-editor">
      <div className="editor-head"><div><Mark tone="gold">PENDING APPROVAL</Mark><strong>WARNING DRAFT</strong><span>ASTRA-W-02491 · Created 08:37 IST</span></div><div role="button" tabIndex={0} onClick={()=>setState("list")}><Icon name="close"/></div></div>
      <div className="human-required"><Icon name="risk"/><div><strong>HUMAN REVIEW REQUIRED</strong><span>ASTRA never automatically dispatches warnings.</span></div></div>
      <div className="warning-instruments">{[["SEVERITY","HIGH"],["ETA","18 MIN"],["CONFIDENCE","91%"],["IMPACT INDEX","82"]].map(([a,b])=><div key={a}><span>{a}</span><strong>{b}</strong></div>)}</div>
      <div className="editor-field"><span>AFFECTED AREAS</span><div contentEditable suppressContentEditableWarning>Nashik · Dhule · Jalgaon <Icon name="edit" size={14}/></div></div>
      <div className="editor-field message"><span>WARNING MESSAGE</span><div contentEditable suppressContentEditableWarning onInput={(e)=>setMessage(e.currentTarget.textContent||"")}>{message}</div><em>{message.length} / 500 · Changes are recorded in the audit trail</em></div>
      <div className="editor-actions"><Action danger>DISMISS</Action><Action><Icon name="edit"/> SAVE EDIT</Action><Action primary onClick={()=>setState("confirm")}>APPROVE <Icon name="arrow"/></Action></div>
    </div>
  </div>;
  return <div className="warning-overlay warning-list-overlay"><div className="overlay-head"><div><span>HUMAN-IN-THE-LOOP OPERATIONS</span><strong>WARNING CENTER</strong><p>5 AI-assisted drafts require forecaster review</p></div><div role="button" tabIndex={0} onClick={returnToMap}><Icon name="close"/></div></div><div className="warning-timeline"><i></i>{drafts.map((w,index)=><div className="warning-draft" key={w[0]}><div className="time-node"><span></span><b>08:{37-index*5}</b></div><div className="draft-main"><div><strong>{w[0]}</strong><Mark tone={w[1].toLowerCase()}>{w[1]}</Mark></div><span>{w[2]}</span></div><div className="draft-stat"><span>ETA</span><strong>{w[3]}</strong></div><div className="draft-stat"><span>IMPACT</span><strong>{w[4]}</strong></div><div className="draft-stat"><span>CONF.</span><strong>{w[5]}</strong></div><Action primary onClick={()=>setState("review")}>REVIEW <Icon name="arrow"/></Action></div>)}</div><div className="warning-policy"><Icon name="risk"/><span>ASTRA prepares warnings for human review. No warning is automatically dispatched.</span></div></div>;
}

function AuditOverlay({ close }: { close: () => void }) {
  const rows = [["08:42:11","ASTRA-W-02491","R. Kumar","APPROVED","Nashik"],["08:39:06","ASTRA-W-02491","R. Kumar","EDITED","Nashik"],["08:37:42","ASTRA-W-02491","ASTRA AI","CREATED","Nashik"],["08:31:18","ASTRA-W-02490","ASTRA AI","CREATED","Hisar"],["08:24:03","ASTRA-W-02489","A. Nair","DISMISSED","Kochi"]];
  return <div className="mode-overlay audit-overlay"><div className="overlay-head"><div><span>IMMUTABLE DECISION RECORD</span><strong>AUDIT CHRONOLOGY</strong><p>27 September 2026 · All times IST</p></div><div role="button" tabIndex={0} onClick={close}><Icon name="close"/></div></div><div className="audit-stream">{rows.map((r,i)=><div className="audit-event" key={r[0]}><span className="audit-time">{r[0]}</span><i className={r[3].toLowerCase()}></i><div><strong>{r[3]}</strong><span>{r[1]} · {r[4]}</span></div><div><span>ACTOR</span><strong>{r[2]}</strong></div><Icon name="chevron"/></div>)}</div></div>;
}

function LandingAtmosphere() {
  const particles = Array.from({ length: 34 }, (_, index) => ({
    x: (index * 37 + 11) % 100,
    y: (index * 61 + 17) % 100,
    delay: index % 9,
    size: index % 4 === 0 ? 2 : 1,
  }));
  return <div className="landing-atmosphere">
    <div className="landing-aurora one"></div><div className="landing-aurora two"></div>
    <div className="landing-cloud cloud-one"></div><div className="landing-cloud cloud-two"></div>
    <div className="landing-grid"></div>
    <svg className="landing-india" viewBox="0 0 400 420" preserveAspectRatio="xMidYMid meet">
      <defs>
        <radialGradient id="landingStorm"><stop stopColor="var(--white-hot)" stopOpacity=".72"/><stop offset=".13" stopColor="var(--magenta)" stopOpacity=".64"/><stop offset=".44" stopColor="var(--violet)" stopOpacity=".3"/><stop offset="1" stopColor="var(--violet)" stopOpacity="0"/></radialGradient>
        <radialGradient id="landingStormCool"><stop stopColor="var(--cyan)" stopOpacity=".55"/><stop offset=".38" stopColor="var(--violet)" stopOpacity=".28"/><stop offset="1" stopColor="var(--violet)" stopOpacity="0"/></radialGradient>
        <filter id="landingGlow"><feGaussianBlur stdDeviation="7"/></filter>
      </defs>
      <path d={indiaPath} className="landing-country"/>
      <g className="landing-states"><path d="M83 116l69 16 57-66M67 146l78 25 99-18M61 190l90 10 89-19M82 232l72-3 64-4M105 278l66-11 36-18M130 337l45-24 11-10M145 171l-2 190M110 65l42 67M210 66l-58 66M245 153l-94 47M207 246l-53-17M286 94l24 26"/></g>
      <g className="landing-storm-field">
        <ellipse cx="116" cy="225" rx="52" ry="38" fill="url(#landingStorm)"/><ellipse cx="126" cy="217" rx="22" ry="17" fill="url(#landingStorm)"/>
        <ellipse cx="287" cy="119" rx="44" ry="31" fill="url(#landingStormCool)"/><ellipse cx="160" cy="318" rx="37" ry="29" fill="url(#landingStormCool)"/>
        <circle cx="116" cy="225" r="2.5"/><circle cx="287" cy="119" r="2"/>
      </g>
      <g className="landing-rain">
        {[[98,208],[106,214],[121,201],[130,214],[137,224],[278,111],[291,104],[299,118],[153,312],[165,325]].map(([x,y],i)=><path key={i} d={`M${x} ${y}l-4 8`}/>)}
      </g>
      <g className="landing-lightning" transform="translate(115 211)"><path d="m4 0-7 11h5l-2 9 9-14H4Z"/></g>
    </svg>
    <div className="landing-particles">{particles.map((p,index)=><i key={index} style={{"--x":`${p.x}%`,"--y":`${p.y}%`,"--delay":`${p.delay}s`,"--particle-size":`${p.size}px`} as React.CSSProperties}></i>)}</div>
    <div className="landing-scan"></div>
  </div>;
}

function CapabilityVisual({ type }: { type: "detect" | "predict" | "assess" }) {
  if (type === "detect") return <div className="capability-visual detect-visual"><div className="cell-ring outer"></div><div className="cell-ring middle"></div><div className="cell-ring core"></div><i></i><span>AST-024 · FORMING</span><em>87%</em></div>;
  if (type === "predict") return <div className="capability-visual predict-visual"><svg viewBox="0 0 440 180"><path className="prediction-cone" d="M35 132 Q210 89 402 25L417 91Q220 117 35 132Z"/><path className="prediction-path" d="M35 132 Q210 89 410 57"/>{[35,110,190,278,360,410].map((x,i)=><g key={x}><circle cx={x} cy={132-i*15} r={i===0?7:4}/><text x={x} y={158-i*15}>+{i*10}</text></g>)}</svg><span>NOW</span><em>+60 MIN</em></div>;
  return <div className="capability-visual assess-visual"><svg viewBox="0 0 440 180"><path className="impact-path" d="M20 145Q164 92 394 32"/><path className="impact-cone" d="M20 145Q180 88 394 13L415 60Q205 112 20 145Z"/><g transform="translate(275 72)"><circle r="18"/><path d="M-7 0h14M0-7v14"/><text x="-34" y="34">DISTRICT HOSPITAL</text></g><g transform="translate(361 37)"><circle r="12"/><path d="M-5 0h10M0-5v10"/></g></svg><div><span>37 FACILITIES EXPOSED</span><em>NEAREST ETA · 14 MIN</em></div></div>;
}

function Landing({ enter }: { enter: () => void }) {
  const [transitioning,setTransitioning]=useState(false);
  const landingRef=useRef<HTMLDivElement>(null);
  const beginEntry=()=>{
    if (transitioning) return;
    setTransitioning(true);
    window.setTimeout(enter,900);
  };
  const move=(event:React.PointerEvent<HTMLDivElement>)=>{
    const bounds=landingRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const x=(event.clientX-bounds.left)/bounds.width-.5;
    const y=(event.clientY-bounds.top)/bounds.height-.5;
    landingRef.current?.style.setProperty("--cursor-x",`${x*10}px`);
    landingRef.current?.style.setProperty("--cursor-y",`${y*7}px`);
  };
  return <div ref={landingRef} className={`landing ${transitioning?"entering":""}`} onPointerMove={move}>
    <LandingAtmosphere/>
    <div className="landing-status"><span><i></i> SYSTEM READY</span><b>27 SEP 2026 · 08:42 IST</b></div>
    <section className="landing-hero">
      <div className="landing-brand"><div className="astra-sigil landing-sigil"><i></i><i></i><i></i><span></span></div><span>AI STORM INTELLIGENCE</span></div>
      <div className="landing-title">ASTRA</div>
      <div className="landing-tagline">See the storm before it strikes.</div>
      <p>AI-powered thunderstorm and lightning nowcasting for India, transforming atmospheric signals into actionable foresight.</p>
      <div className="landing-enter" role="button" tabIndex={0} onClick={beginEntry} onKeyDown={(e)=>e.key==="Enter"&&beginEntry()}><span>ENTER COMMAND CENTER</span><Icon name="arrow"/><i></i></div>
      <div className="landing-telemetry"><span>PAN-INDIA</span><i></i><span>10–60 MIN NOWCAST</span><i></i><span>AI STORM TRACKING</span><i></i><span>HUMAN-IN-THE-LOOP</span></div>
      <div className="scroll-cue"><span>EXPLORE ASTRA</span><i></i></div>
    </section>
    <div className="landing-content">
      <section className="what-is-astra reveal-section"><span className="section-index">00 / SYSTEM</span><div><div className="landing-section-title">From atmospheric signals<br/>to foresight.</div><p>ASTRA combines multiple atmospheric data sources with AI-based nowcasting to detect developing storms, predict their movement, estimate lightning risk, and identify potential impacts across India.</p></div><div className="signal-stack">{["RADAR / PRECIPITATION","SATELLITE","LIGHTNING","GROUND STATIONS","NWP"].map((x,i)=><div key={x}><i style={{"--signal-delay":`${i*.2}s`} as React.CSSProperties}></i><span>{x}</span><em>INGESTING</em></div>)}</div></section>
      <section className="capability-section"><div className="capability-copy"><span className="section-index">01 / DETECT</span><div className="landing-section-title">Identify developing<br/>storm activity.</div><p>Live atmospheric signals resolve into trackable storm objects—before their impact becomes visible on the ground.</p></div><CapabilityVisual type="detect"/></section>
      <section className="capability-section reverse"><div className="capability-copy"><span className="section-index">02 / PREDICT</span><div className="landing-section-title">See where the storm<br/>is heading.</div><p>Follow forecast movement, growth and uncertainty from now through the next 60 minutes.</p></div><CapabilityVisual type="predict"/></section>
      <section className="capability-section"><div className="capability-copy"><span className="section-index">03 / ASSESS</span><div className="landing-section-title">Understand what it could<br/>affect before it arrives.</div><p>Connect projected paths with infrastructure exposure, lightning risk and operational impact.</p></div><CapabilityVisual type="assess"/></section>
      <section className="human-section"><div className="human-orbit"><div className="astra-sigil landing-sigil"><i></i><i></i><i></i><span></span></div><svg viewBox="0 0 220 220"><circle cx="110" cy="110" r="93"/><circle cx="110" cy="110" r="72"/></svg></div><span className="section-index">HUMAN-IN-THE-LOOP</span><div className="landing-section-title">AI-assisted. Human-controlled.</div><p>ASTRA supports forecasters with predictions, risk intelligence, and warning drafts. Every warning remains under explicit human review and approval.</p></section>
      <section className="landing-final"><span>OPERATIONAL INTELLIGENCE · PAN-INDIA DOMAIN</span><div className="landing-section-title">Ready to see what the<br/>atmosphere is doing?</div><div className="landing-enter final" role="button" tabIndex={0} onClick={beginEntry} onKeyDown={(e)=>e.key==="Enter"&&beginEntry()}><span>ENTER ASTRA</span><Icon name="arrow"/><i></i></div><div className="final-coordinates">6–38°N · 68–98°E</div></section>
    </div>
    {transitioning&&<div className="entry-sequence"><div className="entry-reticle"><i></i><i></i><span>INITIALIZING LIVE ATMOSPHERE</span></div></div>}
  </div>;
}

export default function App() {
  const [entered,setEntered]=useState(false);
  const [mode,setMode]=useState<Mode>("Overview");
  const [selected,setSelected]=useState<Storm|null>(null);
  const [horizon,setHorizon]=useState(0);
  const [playing,setPlaying]=useState(false);
  const [layers,setLayers]=useState<Set<Layer>>(new Set(["Probability","Lightning","Tracks"]));
  const [impactExpanded,setImpactExpanded]=useState(false);
  const [degraded,setDegraded]=useState(true);
  const [warningState,setWarningState]=useState<WarningState>("list");

  useEffect(()=>{
    if (!playing) return;
    const timer = window.setInterval(()=>setHorizon((h)=>{
      if (h >= 60) { setPlaying(false); return 60; }
      return h + 10;
    }),900);
    return ()=>window.clearInterval(timer);
  },[playing]);

  const chooseMode=(next:Mode)=>{
    setMode(next);
    if (next==="Warnings") setWarningState("list");
    if (next==="Infrastructure") setLayers((old)=>new Set([...old,"Infrastructure"]));
    if (next==="Risk") setLayers((old)=>new Set([...old,"Risk fields"]));
  };
  const toggleLayer=(layer:Layer)=>setLayers((old)=>{const next=new Set(old);next.has(layer)?next.delete(layer):next.add(layer);return next});
  const returnToMap=()=>{setMode("Overview");setWarningState("list");setSelected(storms[0]);setHorizon(30)};

  if (!entered) return <Landing enter={()=>setEntered(true)}/>;
  return <div className="astra-app command-enter">
    <AtmosphericMap selected={selected} setSelected={(s)=>{setSelected(s);setHorizon(0)}} horizon={horizon} layers={layers} mode={mode}/>
    <div className="vignette"></div>
    <NavRail mode={mode} setMode={chooseMode}/>
    <TopHud setMode={chooseMode}/>
    <Telemetry degraded={degraded}/>
    <div className="mode-label"><span>MODE</span><strong>{mode.toUpperCase()}</strong>{mode!=="Overview"&&<em>{mode==="Nowcast"?"FORECAST EVOLUTION":mode==="Risk"?"EXPOSURE ANALYSIS":mode==="Infrastructure"?"CRITICAL ASSETS":"INTELLIGENCE VIEW"}</em>}</div>
    <LayerControl layers={layers} toggle={toggleLayer}/>
    <DataHealth degraded={degraded} setDegraded={setDegraded}/>
    {selected && <IntelligencePanel storm={selected} close={()=>{setSelected(null);setImpactExpanded(false)}} degraded={degraded} openImpact={()=>setImpactExpanded(true)}/>}
    <ImpactHud expanded={impactExpanded} setExpanded={setImpactExpanded} selected={selected}/>
    {mode==="Overview" && !selected && <div className="discovery-prompt"><Icon name="target"/><div><strong>SELECT AN ATMOSPHERIC SYSTEM</strong><span>Inspect movement, forecast evolution and projected impact</span></div></div>}
    {(mode==="Warnings") && <WarningCenter state={warningState} setState={setWarningState} returnToMap={returnToMap}/>}
    {mode==="Audit" && <AuditOverlay close={()=>setMode("Overview")}/>}
    {mode!=="Warnings" && mode!=="Audit" && <ForecastTimeline horizon={horizon} setHorizon={setHorizon} playing={playing} setPlaying={setPlaying} selected={selected}/>}
    {mode==="Overview" && <div className="warning-beacon" role="button" tabIndex={0} onClick={()=>chooseMode("Warnings")}><Icon name="warning"/><div><strong>5 WARNINGS</strong><span>REQUIRE REVIEW</span></div><Icon name="chevron" size={14}/></div>}
  </div>;
}
