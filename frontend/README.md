# Dive Spot Finder – Frontend

Web client for **Dive Spot Finder**, a platform for discovering cliff jumping spots, monitoring marine water quality and detecting potential oil spills.

Built with **React**, **TypeScript**, **Vite** and **Tailwind CSS**.

## Tech Stack

| Tool | Purpose |
|---|---|
| [React](https://react.dev/) | UI library |
| [TypeScript](https://www.typescriptlang.org/) | Static typing |
| [Vite](https://vite.dev/) | Dev server and build tool |
| [Tailwind CSS v4](https://tailwindcss.com/) | Utility-first styling (via `@tailwindcss/vite`) |

## Prerequisites

- [Node.js](https://nodejs.org/) 20.19+ or 22+
- npm (bundled with Node.js)
- Git

## Getting Started

1. **Clone the repository and open the frontend folder**

   ```bash
   git clone <repository-url>
   cd <repository>/frontend
   ```

2. **Install dependencies**

   ```bash
   npm install
   ```

3. **Configure environment variables**

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` if your backend runs on a different address.

4. **Start the development server**

   ```bash
   npm run dev
   ```

   The app is available at <http://localhost:5173>.

## Available Scripts

| Command | Description |
|---|---|
| `npm run dev` | Start the development server with hot reload |
| `npm run build` | Type-check and create a production build in `dist/` |
| `npm run preview` | Preview the production build locally |
| `npm run lint` | Run ESLint |

## Environment Variables

Environment variables are loaded by Vite from the `.env` file. Only variables prefixed with `VITE_` are exposed to the browser.

| Variable | Description | Default |
|---|---|---|
| `VITE_API_URL` | Base URL of the FastAPI backend | `http://localhost:8000` |

- `.env.example` is committed and documents the required variables.
- `.env` is local only and must **never** be committed.
- Do not store secrets in frontend variables: they are visible to anyone using the app.

Variables are accessed through a single typed module:

```ts
import { env } from '@/config/env'

console.log(env.apiUrl)
```

## Project Structure

```
frontend/
├── public/               # Static assets served as-is
├── src/
│   ├── assets/           # Images, icons, fonts
│   ├── components/
│   │   ├── ui/           # Reusable UI elements (buttons, inputs, cards)
│   │   └── layout/       # Navbar, sidebar, footer
│   ├── config/           # App configuration and env access
│   ├── context/          # React context providers (e.g. authentication)
│   ├── hooks/            # Custom React hooks
│   ├── pages/            # Page-level components (Landing, Login, Dashboard...)
│   ├── routes/           # Route definitions and protected routes
│   ├── services/         # API calls to the backend
│   ├── types/            # Shared TypeScript types (Spot, WaterObservation...)
│   ├── utils/            # Helper functions
│   ├── App.tsx           # Root component
│   ├── index.css         # Tailwind entry point
│   └── main.tsx          # Application entry point
├── .env.example          # Environment variable template
├── index.html
├── package.json
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
└── vite.config.ts
```

## Path Alias

The `@` alias points to the `src/` directory, so you can avoid long relative imports:

```ts
import { env } from '@/config/env'
import Navbar from '@/components/layout/Navbar'
```

It is configured in both `vite.config.ts` (for bundling) and `tsconfig.app.json` (for TypeScript and the editor).

## Tailwind CSS

Tailwind v4 is integrated through the Vite plugin. There is no `tailwind.config.js` or `postcss.config.js`. The only setup needed is this line in `src/index.css`:

```css
@import "tailwindcss";
```

Use utility classes directly in JSX:

```tsx
<h1 className="text-4xl font-bold text-sky-900">Dive Spot Finder</h1>
```

## Verifying the Setup

After `npm run dev`, the home page should show:

- A blue background with white text (Tailwind is working)
- The line `API: http://localhost:8000` (environment variables are working)

Also run `npm run build`: it should finish without TypeScript errors.

## Troubleshooting

- **Tailwind styles are not applied:** make sure `tailwindcss()` is listed in the `plugins` array in `vite.config.ts` and that `src/index.css` contains `@import "tailwindcss";` and is imported in `main.tsx`.
- **`@/...` imports are underlined in the editor:** check the `paths` setting in `tsconfig.app.json` and restart the TypeScript server.
- **`import.meta.env.VITE_API_URL` is `undefined`:** confirm that `.env` exists, the variable starts with `VITE_`, and restart the dev server after editing `.env`.

## Conventions

- Components use PascalCase file names (`Navbar.tsx`); hooks start with `use` (`useAuth.ts`).
- Keep API calls in `services/`, not inside components.
- Define shared data shapes in `types/`.