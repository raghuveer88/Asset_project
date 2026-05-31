import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatMessage, ResponseComponent } from '../models/api.models';
import { KpiCardsComponent } from './kpi-cards.component';
import { DataTableComponent } from './data-table.component';
import { BarChartComponent } from './bar-chart.component';
import { LineChartComponent } from './line-chart.component';
import { SourceListComponent } from './source-list.component';
import { FollowupChipsComponent } from './followup-chips.component';

@Component({
  selector: 'app-message-bubble',
  standalone: true,
  imports: [
    CommonModule,
    KpiCardsComponent,
    DataTableComponent,
    BarChartComponent,
    LineChartComponent,
    SourceListComponent,
    FollowupChipsComponent
  ],
  template: `
    <article class="message" [class.user]="message.role === 'user'">
      <div class="bubble">
        <div class="markdown" [innerHTML]="rendered"></div>
        <ng-container *ngIf="message.response as response">
          <ng-container *ngFor="let component of response.components">
            <app-kpi-cards *ngIf="component.type === 'kpi_cards'" [component]="component"></app-kpi-cards>
            <app-data-table *ngIf="component.type === 'table'" [component]="component"></app-data-table>
            <app-bar-chart *ngIf="component.type === 'bar_chart'" [component]="component"></app-bar-chart>
            <app-line-chart *ngIf="component.type === 'line_chart'" [component]="component"></app-line-chart>
          </ng-container>
          <app-source-list [sources]="response.sources"></app-source-list>
          <app-followup-chips [followups]="response.followups" (selected)="followup.emit($event)"></app-followup-chips>
        </ng-container>
      </div>
    </article>
  `
})
export class MessageBubbleComponent {
  @Input({ required: true }) message!: ChatMessage;
  @Output() followup = new EventEmitter<string>();

  /** Renders markdown-like model output into simple, sanitized HTML. */
  get rendered(): string {
    return this.markdown(this.message.content);
  }

  /** Escapes raw text, then applies a small Markdown subset used by responses. */
  private markdown(input: string): string {
    let escaped = input
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');
    const anchors: string[] = [];
    escaped = escaped
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_match, label: string, url: string) => {
        const anchor = this.anchorHtml(label, url);
        if (!anchor) {
          return label;
        }
        const token = `%%ASSET_AI_LINK_${anchors.length}%%`;
        anchors.push(anchor);
        return token;
      })
      .replace(/(^|[\s(])((https?:\/\/)[^\s<>()]+[^\s<>().,!?;:])/g, (_match, prefix: string, url: string) => {
        const anchor = this.anchorHtml(url, url);
        if (!anchor) {
          return `${prefix}${url}`;
        }
        const token = `%%ASSET_AI_LINK_${anchors.length}%%`;
        anchors.push(anchor);
        return `${prefix}${token}`;
      });
    return escaped
      .replace(/^### (.*)$/gm, '<h3>$1</h3>')
      .replace(/^## (.*)$/gm, '<h2>$1</h2>')
      .replace(/^# (.*)$/gm, '<h1>$1</h1>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/^- (.*)$/gm, '<li>$1</li>')
      .replace(/\n\n/g, '</p><p>')
      .replace(/\n/g, '<br>')
      .replace(/^(.*)$/s, '<p>$1</p>')
      .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
      .replace(/%%ASSET_AI_LINK_(\d+)%%/g, (_match, index: string) => anchors[Number(index)] || '');
  }

  /**
   * Only render clickable links for normal web URLs. Angular still sanitizes
   * [innerHTML], and this keeps unsafe schemes out before HTML is generated.
   */
  private safeHref(rawUrl: string): string | null {
    const decoded = rawUrl.replaceAll('&amp;', '&');
    try {
      const parsed = new URL(decoded);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return null;
      }
      return decoded
        .replaceAll('&', '&amp;')
        .replaceAll('"', '&quot;');
    } catch {
      return null;
    }
  }

  private anchorHtml(label: string, rawUrl: string): string | null {
    const href = this.safeHref(rawUrl);
    if (!href) {
      return null;
    }
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  }
}
