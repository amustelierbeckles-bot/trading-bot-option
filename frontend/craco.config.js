const path = require('path');

module.exports = {
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  style: {
    postcss: {
      loaderOptions: (postcssLoaderOptions) => {
        return postcssLoaderOptions;
      },
    },
  },
  jest: {
    configure: {
      moduleNameMapper: {
        "^axios$": "axios/dist/axios.min.js"
      }
    }
  }
};