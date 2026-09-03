"use client";

import { useEffect } from "react";

const clamp = (value: number, minimum = 0, maximum = 1) =>
  Math.min(maximum, Math.max(minimum, value));

type SceneState = {
  opacity: number;
  rotateY: number;
  scale: number;
  visualScale: number;
  x: number;
};

function sceneState(
  progress: number,
  start: number,
  end: number,
  keepFinal = false,
): SceneState {
  const local = clamp((progress - start) / (end - start));
  const enter = clamp(local / 0.2);
  const exit = keepFinal ? 0 : clamp((local - 0.79) / 0.21);
  const settle = clamp((local - 0.13) / 0.58);

  return {
    opacity: enter * (1 - exit),
    rotateY: (1 - enter) * 5 - exit * 4,
    scale: 0.9 + enter * 0.1 - exit * 0.05,
    visualScale: 0.84 + settle * 0.2,
    x: (1 - enter) * 112 - exit * 112,
  };
}

export function MotionEnhancer() {
  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const hero = document.querySelector<HTMLElement>('[data-motion="hero"]');
    const storyboard = document.querySelector<HTMLElement>('[data-motion="storyboard"]');
    const privacy = document.querySelector<HTMLElement>('[data-motion="privacy"]');
    const statement = document.querySelector<HTMLElement>('[data-motion="statement"]');
    const storyIntro = storyboard?.querySelector<HTMLElement>(".storyboard-intro") || null;
    const storyScenes = storyboard
      ? Array.from(storyboard.querySelectorAll<HTMLElement>("[data-story-scene]"))
      : [];

    if (reducedMotion.matches || !hero || !storyboard || !privacy || !statement) return;

    document.documentElement.classList.add("cinematic-ready");

    let animationFrame = 0;
    let lastHeroProgress = -1;
    let lastHeroCompact = false;
    let lastHeroRelease = -1;
    let lastPrivacyProgress = -1;
    let lastStatementProgress = -1;
    let lastStoryboardProgress = -1;
    let layoutSyncFrame = 0;
    let layoutSyncPass = 0;
    let disposed = false;

    const renderHero = (bounds: DOMRect, viewportHeight: number) => {
      hero.classList.toggle("is-motion-active", bounds.bottom > -viewportHeight * 0.5 && bounds.top < viewportHeight * 1.5);
      const travel = Math.max(bounds.height - viewportHeight, 1);
      const progress = clamp(-bounds.top / travel);
      const compact = window.innerWidth <= 1050;
      const stickyRelease = compact ? 0 : Math.max(viewportHeight - bounds.bottom, 0);
      if (
        Math.abs(progress - lastHeroProgress) < 0.0005 &&
        compact === lastHeroCompact &&
        Math.abs(stickyRelease - lastHeroRelease) < 0.5
      ) return;
      lastHeroProgress = progress;
      lastHeroCompact = compact;
      lastHeroRelease = stickyRelease;
      const copyExit = clamp(progress / (compact ? 0.62 : 0.56));
      const copyX = compact ? 0 : progress * -48;
      const copyY = compact ? progress * -49 : progress * -4;
      const stageX = compact ? 0 : progress * -15;
      const stageY = compact
        ? `${(progress * -12).toFixed(3)}vh`
        : `${stickyRelease.toFixed(3)}px`;
      const stageScale = 1 + progress * (compact ? 0.17 : 0.34);

      hero.style.setProperty("--hero-copy-x", `${copyX.toFixed(3)}vw`);
      hero.style.setProperty("--hero-copy-y", `${copyY.toFixed(3)}vh`);
      hero.style.setProperty("--hero-copy-opacity", `${(1 - copyExit).toFixed(4)}`);
      hero.style.setProperty("--hero-stage-x", `${stageX.toFixed(3)}vw`);
      hero.style.setProperty("--hero-stage-y", stageY);
      hero.style.setProperty("--hero-stage-scale", stageScale.toFixed(4));
      hero.style.setProperty("--hero-window-rotate-y", `${(-4 + progress * 4).toFixed(3)}deg`);
      hero.style.setProperty("--hero-window-rotate-z", `${(1 - progress).toFixed(3)}deg`);
      hero.style.setProperty("--hero-orbit-scale", (1 + progress * 0.58).toFixed(4));
      hero.style.setProperty("--hero-orbit-rotate", `${(progress * 48).toFixed(3)}deg`);
      hero.style.setProperty("--hero-caption-opacity", `${(1 - clamp(progress / 0.34)).toFixed(4)}`);
    };

    const renderStoryboard = (bounds: DOMRect, viewportHeight: number) => {
      storyboard.classList.toggle("is-motion-active", bounds.bottom > -viewportHeight * 0.5 && bounds.top < viewportHeight * 1.5);
      const travel = Math.max(bounds.height - viewportHeight, 1);
      const progress = clamp(-bounds.top / travel);
      if (Math.abs(progress - lastStoryboardProgress) < 0.0005) return;
      lastStoryboardProgress = progress;
      const introBuild = clamp(progress / 0.065);
      const introExit = clamp((progress - 0.07) / 0.065);
      const introOpacity = 1 - introExit;
      const introScale = 0.84 + introBuild * 0.16 + introExit * 0.12;
      const introY = (1 - introBuild) * 8 - introExit * 16;

      if (storyIntro) {
        storyIntro.style.setProperty("--intro-opacity", introOpacity.toFixed(4));
        storyIntro.style.setProperty("--intro-scale", introScale.toFixed(4));
        storyIntro.style.setProperty("--intro-y", `${introY.toFixed(3)}vh`);
      }

      const states = [
        sceneState(progress, 0.1, 0.42),
        sceneState(progress, 0.36, 0.7),
        sceneState(progress, 0.64, 1.02, true),
      ];

      states.forEach((state, index) => {
        const scene = storyScenes[index];
        if (!scene) return;
        scene.style.setProperty("--scene-x", `${state.x.toFixed(3)}vw`);
        scene.style.setProperty("--scene-opacity", state.opacity.toFixed(4));
        scene.style.setProperty("--scene-scale", state.scale.toFixed(4));
        scene.style.setProperty("--scene-rotate-y", `${state.rotateY.toFixed(3)}deg`);
        scene.style.setProperty("--scene-visual-scale", state.visualScale.toFixed(4));
        scene.classList.toggle("is-motion-active", state.opacity > 0.01);
      });

      const activeScene = progress < 0.1 ? -1 : progress < 0.37 ? 0 : progress < 0.66 ? 1 : 2;
      storyboard.dataset.activeScene = String(activeScene);
      storyboard.style.setProperty("--story-progress-opacity", introExit.toFixed(4));
    };

    const renderPrivacy = (bounds: DOMRect, viewportHeight: number) => {
      privacy.classList.toggle("is-motion-active", bounds.bottom > -viewportHeight * 0.5 && bounds.top < viewportHeight * 1.5);
      const enter = clamp((viewportHeight - bounds.top) / (viewportHeight * 0.92));
      if (Math.abs(enter - lastPrivacyProgress) < 0.0005) return;
      lastPrivacyProgress = enter;
      const ease = 1 - Math.pow(1 - enter, 3);

      privacy.style.setProperty("--privacy-copy-x", `${((1 - ease) * -44).toFixed(3)}vw`);
      privacy.style.setProperty("--privacy-diagram-x", `${((1 - ease) * 48).toFixed(3)}vw`);
      privacy.style.setProperty("--privacy-opacity", (0.18 + ease * 0.82).toFixed(4));
      privacy.style.setProperty("--privacy-scale", (0.9 + ease * 0.1).toFixed(4));
      privacy.style.setProperty("--privacy-rotate-y", `${((1 - ease) * -7).toFixed(3)}deg`);
    };

    const renderStatement = (bounds: DOMRect, viewportHeight: number) => {
      statement.classList.toggle("is-motion-active", bounds.bottom > -viewportHeight * 0.5 && bounds.top < viewportHeight * 1.5);
      const enter = clamp((viewportHeight * 0.92 - bounds.top) / (viewportHeight * 0.72));
      if (Math.abs(enter - lastStatementProgress) < 0.0005) return;
      lastStatementProgress = enter;
      const ease = 1 - Math.pow(1 - enter, 3);

      statement.style.setProperty("--statement-scale", (0.78 + ease * 0.22).toFixed(4));
      statement.style.setProperty("--statement-y", `${((1 - ease) * 14).toFixed(3)}vh`);
    };

    const render = () => {
      animationFrame = 0;
      const viewportHeight = Math.max(window.innerHeight, 1);

      // Read geometry first, then perform composited writes below.
      const heroBounds = hero.getBoundingClientRect();
      const storyboardBounds = storyboard.getBoundingClientRect();
      const privacyBounds = privacy.getBoundingClientRect();
      const statementBounds = statement.getBoundingClientRect();

      renderHero(heroBounds, viewportHeight);
      renderStoryboard(storyboardBounds, viewportHeight);
      renderPrivacy(privacyBounds, viewportHeight);
      renderStatement(statementBounds, viewportHeight);
    };

    const scheduleRender = () => {
      if (animationFrame) return;
      animationFrame = window.requestAnimationFrame(render);
    };

    const syncAfterLayout = () => {
      scheduleRender();
      layoutSyncPass += 1;
      if (layoutSyncPass < 4) {
        layoutSyncFrame = window.requestAnimationFrame(syncAfterLayout);
      }
    };

    const motionRegions = [hero, storyboard, privacy, statement];
    const intersectionObserver = new IntersectionObserver(scheduleRender, {
      rootMargin: "100% 0px",
      threshold: [0, 0.01, 0.5, 1],
    });
    motionRegions.forEach((region) => intersectionObserver.observe(region));

    const resizeObserver = new ResizeObserver(scheduleRender);
    motionRegions.forEach((region) => resizeObserver.observe(region));

    window.addEventListener("scroll", scheduleRender, { passive: true });
    window.addEventListener("resize", scheduleRender, { passive: true });
    window.addEventListener("pageshow", scheduleRender);
    window.addEventListener("load", scheduleRender);
    syncAfterLayout();
    document.fonts?.ready.then(() => {
      if (!disposed) scheduleRender();
    });

    return () => {
      disposed = true;
      window.removeEventListener("scroll", scheduleRender);
      window.removeEventListener("resize", scheduleRender);
      window.removeEventListener("pageshow", scheduleRender);
      window.removeEventListener("load", scheduleRender);
      intersectionObserver.disconnect();
      resizeObserver.disconnect();
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      if (layoutSyncFrame) window.cancelAnimationFrame(layoutSyncFrame);
      document.documentElement.classList.remove("cinematic-ready");
    };
  }, []);

  return null;
}
