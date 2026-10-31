/** Local dev proxy; production serves the compiled UI from FastAPI. */
import {defineConfig} from "vite";
export default defineConfig({server:{proxy:Object.fromEntries(
 ["/workspace","/reviews","/mail","/runs"].map(path=>[path,"http://127.0.0.1:8000"]))}});
