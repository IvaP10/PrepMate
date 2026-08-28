(function () {
  var FAVICON = { light: "/images/light.svg", dark: "/images/logo-dark.svg" };
  function applyFavicon(theme) {
    var href = FAVICON[theme];
    var link =
      document.querySelector('link[rel="icon"][data-theme-aware]') ||
      document.querySelector('link[rel="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      link.type = "image/svg+xml";
      document.head.appendChild(link);
    }
    link.setAttribute("data-theme-aware", "true");
    if (!link.getAttribute("href") || link.getAttribute("href").indexOf(href) === -1) {
      link.setAttribute("href", href);
    }
  }
  try {
    var t = localStorage.getItem("prepmate-theme") || localStorage.getItem("interai-theme");
    if (t === "dark") {
      document.documentElement.classList.remove("light");
      document.documentElement.classList.add("dark");
      applyFavicon("dark");
    } else if (t === "light") {
      document.documentElement.classList.remove("dark");
      document.documentElement.classList.add("light");
      applyFavicon("light");
    } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      document.documentElement.classList.remove("light");
      document.documentElement.classList.add("dark");
      applyFavicon("dark");
    } else {
      document.documentElement.classList.remove("dark");
      document.documentElement.classList.add("light");
      applyFavicon("light");
    }
  } catch (e) {}
})();
