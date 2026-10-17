# ReturnIQ web

React + TypeScript + Vite app with a sidebar per role:
- **Start a return** (customer) and **Review queue** (reviewer): Flow A.
- **Product insights** (seller): Flow B product list, report with live progress and clickable evidence, Q&A chat.

Icons come from `lucide-react` and the Inter font from `@fontsource-variable/inter` (both bundled, no CDN).

```bash
cd web
npm install
npm run dev        # http://localhost:5173
```

It talks to the API at `http://localhost:8000`; set `VITE_API_URL` to change that. Start the backend first (see [`../server`](../server/README.md)). Full instructions are in the [root README](../README.md).
