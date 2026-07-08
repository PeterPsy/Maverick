import{r as f,j as R}from"./index-C0Qec5qD.js";const P=`#version 300 es
precision mediump float;

layout(location = 0) in vec4 a_position;

uniform vec2 u_resolution;
uniform float u_pixelRatio;
uniform float u_imageAspectRatio;
uniform float u_originX;
uniform float u_originY;
uniform float u_worldWidth;
uniform float u_worldHeight;
uniform float u_fit;
uniform float u_scale;
uniform float u_rotation;
uniform float u_offsetX;
uniform float u_offsetY;

out vec2 v_objectUV;
out vec2 v_objectBoxSize;
out vec2 v_responsiveUV;
out vec2 v_responsiveBoxGivenSize;
out vec2 v_patternUV;
out vec2 v_patternBoxSize;
out vec2 v_imageUV;

vec3 getBoxSize(float boxRatio, vec2 givenBoxSize) {
  vec2 box = vec2(0.);
  // fit = none
  box.x = boxRatio * min(givenBoxSize.x / boxRatio, givenBoxSize.y);
  float noFitBoxWidth = box.x;
  if (u_fit == 1.) { // fit = contain
    box.x = boxRatio * min(u_resolution.x / boxRatio, u_resolution.y);
  } else if (u_fit == 2.) { // fit = cover
    box.x = boxRatio * max(u_resolution.x / boxRatio, u_resolution.y);
  }
  box.y = box.x / boxRatio;
  return vec3(box, noFitBoxWidth);
}

void main() {
  gl_Position = a_position;

  vec2 uv = gl_Position.xy * .5;
  vec2 boxOrigin = vec2(.5 - u_originX, u_originY - .5);
  vec2 givenBoxSize = vec2(u_worldWidth, u_worldHeight);
  givenBoxSize = max(givenBoxSize, vec2(1.)) * u_pixelRatio;
  float r = u_rotation * 3.14159265358979323846 / 180.;
  mat2 graphicRotation = mat2(cos(r), sin(r), -sin(r), cos(r));
  vec2 graphicOffset = vec2(-u_offsetX, u_offsetY);


  // ===================================================

  float fixedRatio = 1.;
  vec2 fixedRatioBoxGivenSize = vec2(
  (u_worldWidth == 0.) ? u_resolution.x : givenBoxSize.x,
  (u_worldHeight == 0.) ? u_resolution.y : givenBoxSize.y
  );

  v_objectBoxSize = getBoxSize(fixedRatio, fixedRatioBoxGivenSize).xy;
  vec2 objectWorldScale = u_resolution.xy / v_objectBoxSize;

  v_objectUV = uv;
  v_objectUV *= objectWorldScale;
  v_objectUV += boxOrigin * (objectWorldScale - 1.);
  v_objectUV += graphicOffset;
  v_objectUV /= u_scale;
  v_objectUV = graphicRotation * v_objectUV;

  // ===================================================

  v_responsiveBoxGivenSize = vec2(
  (u_worldWidth == 0.) ? u_resolution.x : givenBoxSize.x,
  (u_worldHeight == 0.) ? u_resolution.y : givenBoxSize.y
  );
  float responsiveRatio = v_responsiveBoxGivenSize.x / v_responsiveBoxGivenSize.y;
  vec2 responsiveBoxSize = getBoxSize(responsiveRatio, v_responsiveBoxGivenSize).xy;
  vec2 responsiveBoxScale = u_resolution.xy / responsiveBoxSize;

  #ifdef ADD_HELPERS
  v_responsiveHelperBox = uv;
  v_responsiveHelperBox *= responsiveBoxScale;
  v_responsiveHelperBox += boxOrigin * (responsiveBoxScale - 1.);
  #endif

  v_responsiveUV = uv;
  v_responsiveUV *= responsiveBoxScale;
  v_responsiveUV += boxOrigin * (responsiveBoxScale - 1.);
  v_responsiveUV += graphicOffset;
  v_responsiveUV /= u_scale;
  v_responsiveUV.x *= responsiveRatio;
  v_responsiveUV = graphicRotation * v_responsiveUV;
  v_responsiveUV.x /= responsiveRatio;

  // ===================================================

  float patternBoxRatio = givenBoxSize.x / givenBoxSize.y;
  vec2 patternBoxGivenSize = vec2(
  (u_worldWidth == 0.) ? u_resolution.x : givenBoxSize.x,
  (u_worldHeight == 0.) ? u_resolution.y : givenBoxSize.y
  );
  patternBoxRatio = patternBoxGivenSize.x / patternBoxGivenSize.y;

  vec3 boxSizeData = getBoxSize(patternBoxRatio, patternBoxGivenSize);
  v_patternBoxSize = boxSizeData.xy;
  float patternBoxNoFitBoxWidth = boxSizeData.z;
  vec2 patternBoxScale = u_resolution.xy / v_patternBoxSize;

  v_patternUV = uv;
  v_patternUV += graphicOffset / patternBoxScale;
  v_patternUV += boxOrigin;
  v_patternUV -= boxOrigin / patternBoxScale;
  v_patternUV *= u_resolution.xy;
  v_patternUV /= u_pixelRatio;
  if (u_fit > 0.) {
    v_patternUV *= (patternBoxNoFitBoxWidth / v_patternBoxSize.x);
  }
  v_patternUV /= u_scale;
  v_patternUV = graphicRotation * v_patternUV;
  v_patternUV += boxOrigin / patternBoxScale;
  v_patternUV -= boxOrigin;
  // x100 is a default multiplier between vertex and fragmant shaders
  // we use it to avoid UV presision issues
  v_patternUV *= .01;

  // ===================================================

  vec2 imageBoxSize;
  if (u_fit == 1.) { // contain
    imageBoxSize.x = min(u_resolution.x / u_imageAspectRatio, u_resolution.y) * u_imageAspectRatio;
  } else if (u_fit == 2.) { // cover
    imageBoxSize.x = max(u_resolution.x / u_imageAspectRatio, u_resolution.y) * u_imageAspectRatio;
  } else {
    imageBoxSize.x = min(10.0, 10.0 / u_imageAspectRatio * u_imageAspectRatio);
  }
  imageBoxSize.y = imageBoxSize.x / u_imageAspectRatio;
  vec2 imageBoxScale = u_resolution.xy / imageBoxSize;

  v_imageUV = uv;
  v_imageUV *= imageBoxScale;
  v_imageUV += boxOrigin * (imageBoxScale - 1.);
  v_imageUV += graphicOffset;
  v_imageUV /= u_scale;
  v_imageUV.x *= u_imageAspectRatio;
  v_imageUV = graphicRotation * v_imageUV;
  v_imageUV.x /= u_imageAspectRatio;

  v_imageUV += .5;
  v_imageUV.y = 1. - v_imageUV.y;
}`,y=1920*1080*4;let L=class{parentElement;canvasElement;gl;program=null;uniformLocations={};fragmentShader;rafId=null;lastRenderTime=0;currentFrame=0;speed=0;currentSpeed=0;providedUniforms;mipmaps=[];hasBeenDisposed=!1;resolutionChanged=!0;textures=new Map;minPixelRatio;maxPixelCount;isSafari=F();uniformCache={};textureUnitMap=new Map;ownerDocument;constructor(e,i,r,a,o=0,n=0,s=2,c=y,u=[]){if(e?.nodeType===1)this.parentElement=e;else throw new Error("Paper Shaders: parent element must be an HTMLElement");if(this.ownerDocument=e.ownerDocument,!this.ownerDocument.querySelector("style[data-paper-shader]")){const g=this.ownerDocument.createElement("style");g.innerHTML=C,g.setAttribute("data-paper-shader",""),this.ownerDocument.head.prepend(g)}const l=this.ownerDocument.createElement("canvas");this.canvasElement=l,this.parentElement.prepend(l),this.fragmentShader=i,this.providedUniforms=r,this.mipmaps=u,this.currentFrame=n,this.minPixelRatio=s,this.maxPixelCount=c;const h=l.getContext("webgl2",a);if(!h)throw new Error("Paper Shaders: WebGL is not supported in this browser");this.gl=h,this.initProgram(),this.setupPositionAttribute(),this.setupUniforms(),this.setUniformValues(this.providedUniforms),this.setupResizeObserver(),visualViewport?.addEventListener("resize",this.handleVisualViewportChange),this.setSpeed(o),this.parentElement.setAttribute("data-paper-shader",""),this.parentElement.paperShaderMount=this,this.ownerDocument.addEventListener("visibilitychange",this.handleDocumentVisibilityChange)}initProgram=()=>{const e=I(this.gl,P,this.fragmentShader);e&&(this.program=e)};setupPositionAttribute=()=>{const e=this.gl.getAttribLocation(this.program,"a_position"),i=this.gl.createBuffer();this.gl.bindBuffer(this.gl.ARRAY_BUFFER,i);const r=[-1,-1,1,-1,-1,1,-1,1,1,-1,1,1];this.gl.bufferData(this.gl.ARRAY_BUFFER,new Float32Array(r),this.gl.STATIC_DRAW),this.gl.enableVertexAttribArray(e),this.gl.vertexAttribPointer(e,2,this.gl.FLOAT,!1,0,0)};setupUniforms=()=>{const e={u_time:this.gl.getUniformLocation(this.program,"u_time"),u_pixelRatio:this.gl.getUniformLocation(this.program,"u_pixelRatio"),u_resolution:this.gl.getUniformLocation(this.program,"u_resolution")};Object.entries(this.providedUniforms).forEach(([i,r])=>{if(e[i]=this.gl.getUniformLocation(this.program,i),r instanceof HTMLImageElement){const a=`${i}AspectRatio`;e[a]=this.gl.getUniformLocation(this.program,a)}}),this.uniformLocations=e};renderScale=1;parentWidth=0;parentHeight=0;parentDevicePixelWidth=0;parentDevicePixelHeight=0;devicePixelsSupported=!1;resizeObserver=null;setupResizeObserver=()=>{this.resizeObserver=new ResizeObserver(([e])=>{if(e?.borderBoxSize[0]){const i=e.devicePixelContentBoxSize?.[0];i!==void 0&&(this.devicePixelsSupported=!0,this.parentDevicePixelWidth=i.inlineSize,this.parentDevicePixelHeight=i.blockSize),this.parentWidth=e.borderBoxSize[0].inlineSize,this.parentHeight=e.borderBoxSize[0].blockSize}this.handleResize()}),this.resizeObserver.observe(this.parentElement)};handleVisualViewportChange=()=>{this.resizeObserver?.disconnect(),this.setupResizeObserver()};handleResize=()=>{let e=0,i=0;const r=Math.max(1,window.devicePixelRatio),a=visualViewport?.scale??1;if(this.devicePixelsSupported){const l=Math.max(1,this.minPixelRatio/r);e=this.parentDevicePixelWidth*l*a,i=this.parentDevicePixelHeight*l*a}else{let l=Math.max(r,this.minPixelRatio)*a;if(this.isSafari){const h=D(this.ownerDocument);l*=Math.max(1,h)}e=Math.round(this.parentWidth)*l,i=Math.round(this.parentHeight)*l}const o=Math.sqrt(this.maxPixelCount)/Math.sqrt(e*i),n=Math.min(1,o),s=Math.round(e*n),c=Math.round(i*n),u=s/Math.round(this.parentWidth);(this.canvasElement.width!==s||this.canvasElement.height!==c||this.renderScale!==u)&&(this.renderScale=u,this.canvasElement.width=s,this.canvasElement.height=c,this.resolutionChanged=!0,this.gl.viewport(0,0,this.gl.canvas.width,this.gl.canvas.height),this.render(performance.now()))};render=e=>{if(this.hasBeenDisposed)return;if(this.program===null){console.warn("Tried to render before program or gl was initialized");return}const i=e-this.lastRenderTime;this.lastRenderTime=e,this.currentSpeed!==0&&(this.currentFrame+=i*this.currentSpeed),this.gl.clear(this.gl.COLOR_BUFFER_BIT),this.gl.useProgram(this.program),this.gl.uniform1f(this.uniformLocations.u_time,this.currentFrame*.001),this.resolutionChanged&&(this.gl.uniform2f(this.uniformLocations.u_resolution,this.gl.canvas.width,this.gl.canvas.height),this.gl.uniform1f(this.uniformLocations.u_pixelRatio,this.renderScale),this.resolutionChanged=!1),this.gl.drawArrays(this.gl.TRIANGLES,0,6),this.currentSpeed!==0?this.requestRender():this.rafId=null};requestRender=()=>{this.rafId!==null&&cancelAnimationFrame(this.rafId),this.rafId=requestAnimationFrame(this.render)};setTextureUniform=(e,i)=>{if(!i.complete||i.naturalWidth===0)throw new Error(`Paper Shaders: image for uniform ${e} must be fully loaded`);const r=this.textures.get(e);r&&this.gl.deleteTexture(r),this.textureUnitMap.has(e)||this.textureUnitMap.set(e,this.textureUnitMap.size);const a=this.textureUnitMap.get(e);this.gl.activeTexture(this.gl.TEXTURE0+a);const o=this.gl.createTexture();this.gl.bindTexture(this.gl.TEXTURE_2D,o),this.gl.texParameteri(this.gl.TEXTURE_2D,this.gl.TEXTURE_WRAP_S,this.gl.CLAMP_TO_EDGE),this.gl.texParameteri(this.gl.TEXTURE_2D,this.gl.TEXTURE_WRAP_T,this.gl.CLAMP_TO_EDGE),this.gl.texParameteri(this.gl.TEXTURE_2D,this.gl.TEXTURE_MIN_FILTER,this.gl.LINEAR),this.gl.texParameteri(this.gl.TEXTURE_2D,this.gl.TEXTURE_MAG_FILTER,this.gl.LINEAR),this.gl.texImage2D(this.gl.TEXTURE_2D,0,this.gl.RGBA,this.gl.RGBA,this.gl.UNSIGNED_BYTE,i),this.mipmaps.includes(e)&&(this.gl.generateMipmap(this.gl.TEXTURE_2D),this.gl.texParameteri(this.gl.TEXTURE_2D,this.gl.TEXTURE_MIN_FILTER,this.gl.LINEAR_MIPMAP_LINEAR));const n=this.gl.getError();if(n!==this.gl.NO_ERROR||o===null){console.error("Paper Shaders: WebGL error when uploading texture:",n);return}this.textures.set(e,o);const s=this.uniformLocations[e];if(s){this.gl.uniform1i(s,a);const c=`${e}AspectRatio`,u=this.uniformLocations[c];if(u){const l=i.naturalWidth/i.naturalHeight;this.gl.uniform1f(u,l)}}};areUniformValuesEqual=(e,i)=>e===i?!0:Array.isArray(e)&&Array.isArray(i)&&e.length===i.length?e.every((r,a)=>this.areUniformValuesEqual(r,i[a])):!1;setUniformValues=e=>{this.gl.useProgram(this.program),Object.entries(e).forEach(([i,r])=>{let a=r;if(r instanceof HTMLImageElement&&(a=`${r.src.slice(0,200)}|${r.naturalWidth}x${r.naturalHeight}`),this.areUniformValuesEqual(this.uniformCache[i],a))return;this.uniformCache[i]=a;const o=this.uniformLocations[i];if(!o){console.warn(`Uniform location for ${i} not found`);return}if(r instanceof HTMLImageElement)this.setTextureUniform(i,r);else if(Array.isArray(r)){let n=null,s=null;if(r[0]!==void 0&&Array.isArray(r[0])){const c=r[0].length;if(r.every(u=>u.length===c))n=r.flat(),s=c;else{console.warn(`All child arrays must be the same length for ${i}`);return}}else n=r,s=n.length;switch(s){case 2:this.gl.uniform2fv(o,n);break;case 3:this.gl.uniform3fv(o,n);break;case 4:this.gl.uniform4fv(o,n);break;case 9:this.gl.uniformMatrix3fv(o,!1,n);break;case 16:this.gl.uniformMatrix4fv(o,!1,n);break;default:console.warn(`Unsupported uniform array length: ${s}`)}}else typeof r=="number"?this.gl.uniform1f(o,r):typeof r=="boolean"?this.gl.uniform1i(o,r?1:0):console.warn(`Unsupported uniform type for ${i}: ${typeof r}`)})};getCurrentFrame=()=>this.currentFrame;setFrame=e=>{this.currentFrame=e,this.lastRenderTime=performance.now(),this.render(performance.now())};setSpeed=(e=1)=>{this.speed=e,this.setCurrentSpeed(this.ownerDocument.hidden?0:e)};setCurrentSpeed=e=>{this.currentSpeed=e,this.rafId===null&&e!==0&&(this.lastRenderTime=performance.now(),this.rafId=requestAnimationFrame(this.render)),this.rafId!==null&&e===0&&(cancelAnimationFrame(this.rafId),this.rafId=null)};setMaxPixelCount=(e=y)=>{this.maxPixelCount=e,this.handleResize()};setMinPixelRatio=(e=2)=>{this.minPixelRatio=e,this.handleResize()};setUniforms=e=>{this.setUniformValues(e),this.providedUniforms={...this.providedUniforms,...e},this.render(performance.now())};handleDocumentVisibilityChange=()=>{this.setCurrentSpeed(this.ownerDocument.hidden?0:this.speed)};dispose=()=>{this.hasBeenDisposed=!0,this.rafId!==null&&(cancelAnimationFrame(this.rafId),this.rafId=null),this.gl&&this.program&&(this.textures.forEach(e=>{this.gl.deleteTexture(e)}),this.textures.clear(),this.gl.deleteProgram(this.program),this.program=null,this.gl.bindBuffer(this.gl.ARRAY_BUFFER,null),this.gl.bindBuffer(this.gl.ELEMENT_ARRAY_BUFFER,null),this.gl.bindRenderbuffer(this.gl.RENDERBUFFER,null),this.gl.bindFramebuffer(this.gl.FRAMEBUFFER,null),this.gl.getError()),this.resizeObserver&&(this.resizeObserver.disconnect(),this.resizeObserver=null),visualViewport?.removeEventListener("resize",this.handleVisualViewportChange),this.ownerDocument.removeEventListener("visibilitychange",this.handleDocumentVisibilityChange),this.uniformLocations={},this.canvasElement.remove(),delete this.parentElement.paperShaderMount}};function A(t,e,i){const r=t.createShader(e);return r?(t.shaderSource(r,i),t.compileShader(r),t.getShaderParameter(r,t.COMPILE_STATUS)?r:(console.error("An error occurred compiling the shaders: "+t.getShaderInfoLog(r)),t.deleteShader(r),null)):null}function I(t,e,i){const r=t.getShaderPrecisionFormat(t.FRAGMENT_SHADER,t.MEDIUM_FLOAT),a=r?r.precision:null;a&&a<23&&(e=e.replace(/precision\s+(lowp|mediump)\s+float;/g,"precision highp float;"),i=i.replace(/precision\s+(lowp|mediump)\s+float/g,"precision highp float").replace(/\b(uniform|varying|attribute)\s+(lowp|mediump)\s+(\w+)/g,"$1 highp $3"));const o=A(t,t.VERTEX_SHADER,e),n=A(t,t.FRAGMENT_SHADER,i);if(!o||!n)return null;const s=t.createProgram();return s?(t.attachShader(s,o),t.attachShader(s,n),t.linkProgram(s),t.getProgramParameter(s,t.LINK_STATUS)?(t.detachShader(s,o),t.detachShader(s,n),t.deleteShader(o),t.deleteShader(n),s):(console.error("Unable to initialize the shader program: "+t.getProgramInfoLog(s)),t.deleteProgram(s),t.deleteShader(o),t.deleteShader(n),null)):null}const C=`@layer paper-shaders {
  :where([data-paper-shader]) {
    isolation: isolate;
    position: relative;

    & canvas {
      contain: strict;
      display: block;
      position: absolute;
      inset: 0;
      z-index: -1;
      width: 100%;
      height: 100%;
      border-radius: inherit;
      corner-shape: inherit;
    }
  }
}`;function F(){const t=navigator.userAgent.toLowerCase();return t.includes("safari")&&!t.includes("chrome")&&!t.includes("android")}function D(t){const e=visualViewport?.scale??1,i=visualViewport?.width??window.innerWidth,r=window.innerWidth-t.documentElement.clientWidth,a=e*i+r,o=outerWidth/a,n=Math.round(100*o);return n%5===0?n/100:n===33?1/3:n===67?2/3:n===133?4/3:o}const W={fit:"contain",scale:1,rotation:0,offsetX:0,offsetY:0,originX:.5,originY:.5,worldWidth:0,worldHeight:0},H={none:0,contain:1,cover:2},j=`
#define TWO_PI 6.28318530718
#define PI 3.14159265358979323846
`,G=`
vec2 rotate(vec2 uv, float th) {
  return mat2(cos(th), sin(th), -sin(th), cos(th)) * uv;
}
`,X=`
  float hash21(vec2 p) {
    p = fract(p * vec2(0.3183099, 0.3678794)) + 0.1;
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
  }
`,B={maxColorCount:10},N=`#version 300 es
precision mediump float;

uniform float u_time;

uniform vec4 u_colors[${B.maxColorCount}];
uniform float u_colorsCount;

uniform float u_distortion;
uniform float u_swirl;
uniform float u_grainMixer;
uniform float u_grainOverlay;

in vec2 v_objectUV;
out vec4 fragColor;

${j}
${G}
${X}

float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

float noise(vec2 n, vec2 seedOffset) {
  return valueNoise(n + seedOffset);
}

vec2 getPosition(int i, float t) {
  float a = float(i) * .37;
  float b = .6 + fract(float(i) / 3.) * .9;
  float c = .8 + fract(float(i + 1) / 4.);

  float x = sin(t * b + a);
  float y = cos(t * c + a * 1.5);

  return .5 + .5 * vec2(x, y);
}

void main() {
  vec2 uv = v_objectUV;
  uv += .5;
  vec2 grainUV = uv * 1000.;

  float grain = noise(grainUV, vec2(0.));
  float mixerGrain = .4 * u_grainMixer * (grain - .5);

  const float firstFrameOffset = 41.5;
  float t = .5 * (u_time + firstFrameOffset);

  float radius = smoothstep(0., 1., length(uv - .5));
  float center = 1. - radius;
  for (float i = 1.; i <= 2.; i++) {
    uv.x += u_distortion * center / i * sin(t + i * .4 * smoothstep(.0, 1., uv.y)) * cos(.2 * t + i * 2.4 * smoothstep(.0, 1., uv.y));
    uv.y += u_distortion * center / i * cos(t + i * 2. * smoothstep(.0, 1., uv.x));
  }

  vec2 uvRotated = uv;
  uvRotated -= vec2(.5);
  float angle = 3. * u_swirl * radius;
  uvRotated = rotate(uvRotated, -angle);
  uvRotated += vec2(.5);

  vec3 color = vec3(0.);
  float opacity = 0.;
  float totalWeight = 0.;

  for (int i = 0; i < ${B.maxColorCount}; i++) {
    if (i >= int(u_colorsCount)) break;

    vec2 pos = getPosition(i, t) + mixerGrain;
    vec3 colorFraction = u_colors[i].rgb * u_colors[i].a;
    float opacityFraction = u_colors[i].a;

    float dist = length(uvRotated - pos);

    dist = pow(dist, 3.5);
    float weight = 1. / (dist + 1e-3);
    color += colorFraction * weight;
    opacity += opacityFraction * weight;
    totalWeight += weight;
  }

  color /= max(1e-4, totalWeight);
  opacity /= max(1e-4, totalWeight);

  float grainOverlay = valueNoise(rotate(grainUV, 1.) + vec2(3.));
  grainOverlay = mix(grainOverlay, valueNoise(rotate(grainUV, 2.) + vec2(-1.)), .5);
  grainOverlay = pow(grainOverlay, 1.3);

  float grainOverlayV = grainOverlay * 2. - 1.;
  vec3 grainOverlayColor = vec3(step(0., grainOverlayV));
  float grainOverlayStrength = u_grainOverlay * abs(grainOverlayV);
  grainOverlayStrength = pow(grainOverlayStrength, .8);
  color = mix(color, grainOverlayColor, .35 * grainOverlayStrength);

  opacity += .5 * grainOverlayStrength;
  opacity = clamp(opacity, 0., 1.);

  fragColor = vec4(color, opacity);
}
`;function $(t){if(Array.isArray(t))return t.length===4?t:t.length===3?[...t,1]:U;if(typeof t!="string")return U;let e,i,r,a=1;if(t.startsWith("#"))[e,i,r,a]=Y(t);else if(t.startsWith("rgb"))[e,i,r,a]=q(t);else if(t.startsWith("hsl"))[e,i,r,a]=K(k(t));else return console.error("Unsupported color format",t),U;return[b(e,0,1),b(i,0,1),b(r,0,1),b(a,0,1)]}function Y(t){t=t.replace(/^#/,""),t.length===3&&(t=t.split("").map(o=>o+o).join("")),t.length===6&&(t=t+"ff");const e=parseInt(t.slice(0,2),16)/255,i=parseInt(t.slice(2,4),16)/255,r=parseInt(t.slice(4,6),16)/255,a=parseInt(t.slice(6,8),16)/255;return[e,i,r,a]}function q(t){const e=t.match(/^rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+))?\s*\)$/i);return e?[parseInt(e[1]??"0")/255,parseInt(e[2]??"0")/255,parseInt(e[3]??"0")/255,e[4]===void 0?1:parseFloat(e[4])]:[0,0,0,1]}function k(t){const e=t.match(/^hsla?\s*\(\s*(\d+)\s*,\s*(\d+)%\s*,\s*(\d+)%\s*(?:,\s*([0-9.]+))?\s*\)$/i);return e?[parseInt(e[1]??"0"),parseInt(e[2]??"0"),parseInt(e[3]??"0"),e[4]===void 0?1:parseFloat(e[4])]:[0,0,0,1]}function K(t){const[e,i,r,a]=t,o=e/360,n=i/100,s=r/100;let c,u,l;if(i===0)c=u=l=s;else{const h=(m,_,p)=>(p<0&&(p+=1),p>1&&(p-=1),p<.16666666666666666?m+(_-m)*6*p:p<.5?_:p<.6666666666666666?m+(_-m)*(.6666666666666666-p)*6:m),g=s<.5?s*(1+n):s+n-s*n,x=2*s-g;c=h(x,g,o+1/3),u=h(x,g,o),l=h(x,g,o-1/3)}return[c,u,l,a]}const b=(t,e,i)=>Math.min(Math.max(t,e),i),U=[0,0,0,1],Z="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";function Q(t){const e=f.useRef(void 0),i=f.useCallback(r=>{const a=t.map(o=>{if(o!=null){if(typeof o=="function"){const n=o,s=n(r);return typeof s=="function"?s:()=>{n(null)}}return o.current=r,()=>{o.current=null}}});return()=>{a.forEach(o=>o?.())}},t);return f.useMemo(()=>t.every(r=>r==null)?null:r=>{e.current&&(e.current(),e.current=void 0),r!=null&&(e.current=i(r))},t)}function z(t){if(t.naturalWidth<1024&&t.naturalHeight<1024){if(t.naturalWidth<1||t.naturalHeight<1)return;const e=t.naturalWidth/t.naturalHeight;t.width=Math.round(e>1?1024*e:1024),t.height=Math.round(e>1?1024:1024/e)}}async function M(t){const e={},i=[],r=o=>{try{return o.startsWith("/")||new URL(o),!0}catch{return!1}},a=o=>{try{return o.startsWith("/")?!1:new URL(o,window.location.origin).origin!==window.location.origin}catch{return!1}};return Object.entries(t).forEach(([o,n])=>{if(typeof n=="string"){const s=n||Z;if(!r(s)){console.warn(`Uniform "${o}" has invalid URL "${s}". Skipping image loading.`);return}const c=new Promise((u,l)=>{const h=new Image;a(s)&&(h.crossOrigin="anonymous"),h.onload=()=>{z(h),e[o]=h,u()},h.onerror=()=>{console.error(`Could not set uniforms. Failed to load image at ${s}`),l()},h.src=s});i.push(c)}else n instanceof HTMLImageElement&&z(n),e[o]=n}),await Promise.all(i),e}const V=f.forwardRef(function({fragmentShader:e,uniforms:i,webGlContextAttributes:r,speed:a=0,frame:o=0,width:n,height:s,minPixelRatio:c,maxPixelCount:u,mipmaps:l,style:h,...g},x){const[m,_]=f.useState(!1),p=f.useRef(null),v=f.useRef(null),S=f.useRef(r);f.useEffect(()=>((async()=>{const w=await M(i);p.current&&!v.current&&(v.current=new L(p.current,e,w,S.current,a,o,c,u,l),_(!0))})(),()=>{v.current?.dispose(),v.current=null}),[e]),f.useEffect(()=>{let E=!1;return(async()=>{const O=await M(i);E||v.current?.setUniforms(O)})(),()=>{E=!0}},[i,m]),f.useEffect(()=>{v.current?.setSpeed(a)},[a,m]),f.useEffect(()=>{v.current?.setMaxPixelCount(u)},[u,m]),f.useEffect(()=>{v.current?.setMinPixelRatio(c)},[c,m]),f.useEffect(()=>{v.current?.setFrame(o)},[o,m]);const T=Q([p,x]);return R.jsx("div",{ref:T,style:n!==void 0||s!==void 0?{width:typeof n=="string"&&isNaN(+n)===!1?+n:n,height:typeof s=="string"&&isNaN(+s)===!1?+s:s,...h}:h,...g})});V.displayName="ShaderMount";function J(t,e){for(const i in t){if(i==="colors"){const r=Array.isArray(t.colors),a=Array.isArray(e.colors);if(!r||!a){if(Object.is(t.colors,e.colors)===!1)return!1;continue}if(t.colors?.length!==e.colors?.length||!t.colors?.every((o,n)=>o===e.colors?.[n]))return!1;continue}if(Object.is(t[i],e[i])===!1)return!1}return!0}const d={params:{...W,speed:1,frame:0,colors:["#e0eaff","#241d9a","#f75092","#9f50d3"],distortion:.8,swirl:.1,grainMixer:0,grainOverlay:0}},ee=f.memo(function({speed:e=d.params.speed,frame:i=d.params.frame,colors:r=d.params.colors,distortion:a=d.params.distortion,swirl:o=d.params.swirl,grainMixer:n=d.params.grainMixer,grainOverlay:s=d.params.grainOverlay,fit:c=d.params.fit,rotation:u=d.params.rotation,scale:l=d.params.scale,originX:h=d.params.originX,originY:g=d.params.originY,offsetX:x=d.params.offsetX,offsetY:m=d.params.offsetY,worldWidth:_=d.params.worldWidth,worldHeight:p=d.params.worldHeight,...v}){const S={u_colors:r.map($),u_colorsCount:r.length,u_distortion:a,u_swirl:o,u_grainMixer:n,u_grainOverlay:s,u_fit:H[c],u_rotation:u,u_scale:l,u_offsetX:x,u_offsetY:m,u_originX:h,u_originY:g,u_worldWidth:_,u_worldHeight:p};return R.jsx(V,{...v,speed:e,frame:i,fragmentShader:N,uniforms:S})},J);function oe(){const[t,e]=f.useState(te);return f.useEffect(()=>{if(typeof window>"u"||typeof window.matchMedia!="function")return;const i=window.matchMedia("(prefers-reduced-motion: reduce)"),r=()=>e(i.matches);return r(),i.addEventListener("change",r),()=>i.removeEventListener("change",r)},[]),t?R.jsx("div",{className:"bs-login-paper-bg is-static","aria-hidden":"true"}):R.jsx("div",{className:"bs-login-paper-bg","aria-hidden":"true",children:R.jsx(ee,{className:"bs-login-paper-bg__shader",colors:["#000000","#1a1a1a","#333333","#ffffff"],speed:1,maxPixelCount:16e5})})}function te(){return typeof window>"u"||typeof window.matchMedia!="function"?!1:window.matchMedia("(prefers-reduced-motion: reduce)").matches}export{oe as LoginPaperBackground};
