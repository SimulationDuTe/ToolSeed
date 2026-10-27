import z from '@deepseek-ai/schemastery';
import {createReader,createFetchHandler} from './backend.js';
import {installOpportunityHooks} from './opportunities.js';
import {installLearningHooks} from './learning.js';
import {installRecallHooks} from './recall.js';
import {installRevisionValidation} from './revisions.js';
export const name = 'toolseed-panel';
export const inject = ['connection'];
export const Config = z.object({python:z.string().default('python'),dataDir:z.string().default(''),
  opportunities:z.boolean().default(true),mcpServer:z.string().default('toolseed'),
  opportunityDiagnostics:z.boolean().default(false),learning:z.boolean().default(true),
  recall:z.boolean().default(true),recallNamespace:z.string().default(''),
  revisionValidation:z.boolean().default(true)});
export function apply(ctx, config) {
  const lifetime=new AbortController();
  ctx.effect(()=>()=>lifetime.abort());
  // Connection owns browser authentication, owner-only access and Desktop IPC.
  // Registering on webServer directly would bypass that shared admission boundary.
  ctx.connection.fetch.register({path:'/api/toolseed.read',methods:['POST'],requestBody:'buffered',
    fetch:createFetchHandler(createReader(config),lifetime.signal)});
  if (config.opportunities !== false || config.learning !== false || config.recall !== false || config.revisionValidation !== false) {
    // Optional services: the read-only settings panel still works without an
    // Agent runtime. Cordis owns injection/listener lifetimes and disposal.
    ctx.inject(['agents','tools'], host => {
      if (config.opportunities !== false) installOpportunityHooks(host,config);
      if (config.learning !== false) installLearningHooks(host,config);
      if (config.recall !== false) installRecallHooks(host,config);
      if (config.revisionValidation !== false) installRevisionValidation(host,config);
    });
  }
}
