import z from '@deepseek-ai/schemastery';
import {createReader,createFetchHandler} from './backend.js';
import {installOpportunityHooks} from './opportunities.js';
export const name = 'toolseed-panel';
export const inject = ['connection'];
export const Config = z.object({python:z.string().default('python'),dataDir:z.string().default(''),
  opportunities:z.boolean().default(true),mcpServer:z.string().default('toolseed'),
  opportunityDiagnostics:z.boolean().default(false)});
export function apply(ctx, config) {
  const lifetime=new AbortController();
  ctx.effect(()=>()=>lifetime.abort());
  // Connection owns browser authentication, owner-only access and Desktop IPC.
  // Registering on webServer directly would bypass that shared admission boundary.
  ctx.connection.fetch.register({path:'/api/toolseed.read',methods:['POST'],requestBody:'buffered',
    fetch:createFetchHandler(createReader(config),lifetime.signal)});
  if (config.opportunities !== false) {
    // Optional services: the read-only settings panel still works without an
    // Agent runtime. Cordis owns injection/listener lifetimes and disposal.
    ctx.inject(['agents','tools'], host => installOpportunityHooks(host,config));
  }
}
