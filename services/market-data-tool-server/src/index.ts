import { createServer } from "./server.js";
import { config } from "./config.js";

const app = createServer();

app.listen(config.port, () => {
  console.log(`market-data-tool-server listening on :${config.port}`);
});
