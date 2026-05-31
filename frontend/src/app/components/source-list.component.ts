import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Source } from '../models/api.models';

@Component({
  selector: 'app-source-list',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="sources" *ngIf="sources.length">
      <h3>Sources</h3>
      <article class="source-card" *ngFor="let source of sources">
        <a [href]="source.url || '#'" target="_blank" rel="noopener noreferrer">
          <strong>{{ source.title || 'Property website' }}</strong>
        </a>
        <span [innerHTML]="linkifiedSnippet(source.snippet)"></span>
      </article>
    </section>
  `
})
export class SourceListComponent {
  @Input({ required: true }) sources: Source[] = [];

  linkifiedSnippet(snippet: string | null | undefined): string {
    const escaped = String(snippet || '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');
    return escaped.replace(/(^|[\s(])((https?:\/\/)[^\s<>()]+[^\s<>().,!?;:])/g, (_match, prefix: string, url: string) => {
      const href = this.safeHref(url);
      if (!href) {
        return `${prefix}${url}`;
      }
      return `${prefix}<a href="${href}" target="_blank" rel="noopener noreferrer">${url}</a>`;
    });
  }

  private safeHref(rawUrl: string): string | null {
    const decoded = rawUrl.replaceAll('&amp;', '&');
    try {
      const parsed = new URL(decoded);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return null;
      }
      return decoded.replaceAll('&', '&amp;').replaceAll('"', '&quot;');
    } catch {
      return null;
    }
  }
}
