// craco.config.js
const path = require("path");
require("dotenv").config();
const { GenerateSW } = require("workbox-webpack-plugin");

// Check if we're in development/preview mode (not production build)
// Craco sets NODE_ENV=development for start, NODE_ENV=production for build
const isDevServer = process.env.NODE_ENV !== "production";

// Environment variable overrides
const config = {
  enableHealthCheck: process.env.ENABLE_HEALTH_CHECK === "true",
};

// Conditionally load health check modules only if enabled
let WebpackHealthPlugin;
let setupHealthEndpoints;
let healthPluginInstance;

if (config.enableHealthCheck) {
  WebpackHealthPlugin = require("./plugins/health-check/webpack-health-plugin");
  setupHealthEndpoints = require("./plugins/health-check/health-endpoints");
  healthPluginInstance = new WebpackHealthPlugin();
}

let webpackConfig = {
  eslint: {
    configure: {
      extends: ["plugin:react-hooks/recommended"],
      rules: {
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
      },
    },
  },
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    configure: (webpackConfig) => {

      // Add ignored patterns to reduce watched directories
        webpackConfig.watchOptions = {
          ...webpackConfig.watchOptions,
          ignored: [
            '**/node_modules/**',
            '**/.git/**',
            '**/build/**',
            '**/dist/**',
            '**/coverage/**',
            '**/public/**',
        ],
      };

      // Add health check plugin to webpack if enabled
      if (config.enableHealthCheck && healthPluginInstance) {
        webpackConfig.plugins.push(healthPluginInstance);
      }

      // PWA Service Worker (production builds only)
      if (process.env.NODE_ENV === "production") {
        webpackConfig.plugins.push(
          new GenerateSW({
            swDest: "service-worker.js",
            clientsClaim: true,
            skipWaiting: false,
            cleanupOutdatedCaches: true,
            exclude: [/\.map$/, /asset-manifest\.json$/, /LICENSE/, /enrichment-dump\.json$/],
            maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
            navigateFallback: "/index.html",
            navigateFallbackDenylist: [/^\/api\//, /^\/admin/, /\/[^/]+\.[^/]+$/],
            runtimeCaching: [
              {
                // JSON API — fresh data preferred, falling back to cache (≤ 10 min).
                urlPattern: ({ url }) => url.origin === self.location.origin && url.pathname.startsWith("/api/"),
                handler: "NetworkFirst",
                options: {
                  cacheName: "api-cache",
                  networkTimeoutSeconds: 5,
                  expiration: { maxEntries: 200, maxAgeSeconds: 600 },
                  cacheableResponse: { statuses: [0, 200] },
                },
              },
              {
                // Same-origin images: long cache
                urlPattern: ({ url, request }) => url.origin === self.location.origin && request.destination === "image",
                handler: "CacheFirst",
                options: {
                  cacheName: "image-cache",
                  expiration: { maxEntries: 400, maxAgeSeconds: 30 * 24 * 60 * 60, purgeOnQuotaError: true },
                  cacheableResponse: { statuses: [0, 200] },
                },
              },
              {
                // Same-origin fonts/css/js (rare since precached): SWR
                urlPattern: ({ url, request }) =>
                  url.origin === self.location.origin &&
                  (request.destination === "style" || request.destination === "script" || request.destination === "font"),
                handler: "StaleWhileRevalidate",
                options: { cacheName: "static-assets-cache" },
              },
            ],
          })
        );
      }

      return webpackConfig;
    },
  },
};

webpackConfig.devServer = (devServerConfig) => {
  // Add health check endpoints if enabled
  if (config.enableHealthCheck && setupHealthEndpoints && healthPluginInstance) {
    const originalSetupMiddlewares = devServerConfig.setupMiddlewares;

    devServerConfig.setupMiddlewares = (middlewares, devServer) => {
      // Call original setup if exists
      if (originalSetupMiddlewares) {
        middlewares = originalSetupMiddlewares(middlewares, devServer);
      }

      // Setup health endpoints
      setupHealthEndpoints(devServer, healthPluginInstance);

      return middlewares;
    };
  }

  return devServerConfig;
};

// Wrap with visual edits (automatically adds babel plugin, dev server, and overlay in dev mode)
if (isDevServer) {
  try {
    const { withVisualEdits } = require("@emergentbase/visual-edits/craco");
    webpackConfig = withVisualEdits(webpackConfig);
  } catch (err) {
    if (err.code === 'MODULE_NOT_FOUND' && err.message.includes('@emergentbase/visual-edits/craco')) {
      console.warn(
        "[visual-edits] @emergentbase/visual-edits not installed — visual editing disabled."
      );
    } else {
      throw err;
    }
  }
}

module.exports = webpackConfig;
