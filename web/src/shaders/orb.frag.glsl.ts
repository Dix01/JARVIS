// Fragment shader — Fresnel-glow rim + state-tinted core + iridescence.
export default /* glsl */`
  uniform float uTime;
  uniform vec3  uColorA;
  uniform vec3  uColorB;
  uniform float uGlow;
  uniform float uAudio;

  varying vec3 vNormal;
  varying vec3 vPos;
  varying float vDisp;

  void main() {
    vec3 viewDir = normalize(-vPos);
    float fres = pow(1.0 - max(dot(normalize(vNormal), viewDir), 0.0), 2.2);

    // Color blend between two state-driven colors based on vertex displacement
    float t = smoothstep(-0.4, 0.6, vDisp + uAudio * 0.5);
    vec3 base = mix(uColorA, uColorB, t);

    // Iridescent shimmer
    float shimmer = 0.5 + 0.5 * sin(vPos.y * 6.0 + uTime * 1.4);
    base += vec3(shimmer * 0.05, shimmer * 0.08, shimmer * 0.1);

    // Pulse on audio
    float pulse = 0.7 + 0.6 * uAudio;
    vec3 color = base * pulse + fres * uGlow * uColorB;

    // Inner core brightness
    float core = pow(max(dot(normalize(vNormal), viewDir), 0.0), 4.0) * 0.6;
    color += core * uColorA;

    gl_FragColor = vec4(color, 0.94);
  }
`;
