import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#1e3a5f',
          50: '#e8eef5',
          100: '#d1ddf0',
          200: '#a3bbe0',
          300: '#7599d1',
          400: '#4777c1',
          500: '#1e3a5f',
          600: '#1a3252',
          700: '#152a45',
          800: '#102238',
          900: '#0b1a2b',
        },
        accent: {
          DEFAULT: '#c9a227',
          50: '#fbf6e3',
          100: '#f7edc7',
          200: '#efdb8f',
          300: '#e7c957',
          400: '#c9a227',
          500: '#b08e22',
          600: '#977a1d',
          700: '#7e6618',
          800: '#655213',
          900: '#4c3e0e',
        },
      },
    },
  },
  plugins: [],
};

export default config;
