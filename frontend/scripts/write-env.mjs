import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const apiBaseUrl = process.env.API_BASE_URL || 'http://localhost:8000/api';
const target = resolve('src/environments/environment.ts');
const content = `export const environment = {
  apiBaseUrl: '${apiBaseUrl.replaceAll("'", "\\'")}'
};
`;

mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, content, 'utf8');
