export function getScoreInfo(score) {
  if (score >= 85) return { color: '#43fe6d', label: 'Sinema İkizleri ✦✦✦', bg: 'rgba(0,224,84,' };
  if (score >= 70) return { color: '#40BCF4', label: 'Film Yoldaşları ✦✦', bg: 'rgba(64,188,244,' };
  if (score >= 50) return { color: '#ffb787', label: 'Farklı Dünyalar ✦', bg: 'rgba(255,183,135,' };
  if (score >= 30) return { color: '#ff8000', label: 'Kesişen Yollar', bg: 'rgba(255,128,0,' };
  return { color: '#ffb4ab', label: 'Zıt Kutuplar', bg: 'rgba(255,180,171,' };
}

export function animateScore(target, ringEl, numberEl, duration = 1400) {
  const circumference = 503;
  const start = performance.now();
  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(eased * target);
    numberEl.textContent = current;
    ringEl.style.strokeDashoffset = circumference * (1 - current / 100);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
