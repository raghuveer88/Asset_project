import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ResponseComponent } from '../models/api.models';

@Component({
  selector: 'app-line-chart',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="component-block">
      <h3>{{ component.title }}</h3>
      <p class="empty-state" *ngIf="!hasData">No data available for this view.</p>
      <svg class="line-chart" *ngIf="hasData" viewBox="0 0 640 220" role="img">
        <line x1="58" y1="18" x2="58" y2="178" class="axis"></line>
        <line x1="58" y1="178" x2="618" y2="178" class="axis"></line>
        <g *ngFor="let tick of yTicks">
          <line x1="54" x2="618" [attr.y1]="tick.y" [attr.y2]="tick.y" class="grid"></line>
          <text x="48" [attr.y]="tick.y + 4" text-anchor="end">{{ tick.label }}</text>
        </g>
        <polyline [attr.points]="points" fill="none" stroke="#0f766e" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>
        <g *ngFor="let point of pointList">
          <circle [attr.cx]="point.x" [attr.cy]="point.y" r="4" fill="#0f766e">
            <title>{{ point.label }}: {{ point.displayValue }}</title>
          </circle>
          <text *ngIf="point.showLabel" [attr.x]="point.x" y="204" text-anchor="middle">{{ point.label }}</text>
        </g>
      </svg>
    </section>
  `
})
export class LineChartComponent {
  @Input({ required: true }) component!: ResponseComponent;

  get data(): Record<string, unknown>[] {
    return this.component.data || [];
  }

  get yKey(): string {
    return this.component.y_key || 'value';
  }

  get xKey(): string {
    return this.component.x_key || 'label';
  }

  get hasData(): boolean {
    return this.data.length > 0 && this.data.some((row) => row[this.xKey] !== undefined && row[this.yKey] !== undefined);
  }

  get isPercentChart(): boolean {
    return this.yKey.includes('rate') || this.yKey.includes('percent') || this.component.title.toLowerCase().includes('occupancy');
  }

  get isMoneyChart(): boolean {
    return ['rent', 'loss', 'balance', 'amount', 'charge'].some((token) => this.yKey.includes(token));
  }

  get yDomain(): { min: number; max: number } {
    const values = this.data.map((row) => Number(row[this.yKey]) || 0);
    if (!values.length) {
      return { min: 0, max: 100 };
    }
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    if (this.isPercentChart && rawMin >= 90 && rawMax <= 100) {
      return { min: 90, max: 100 };
    }
    const padding = Math.max((rawMax - rawMin) * 0.15, this.isPercentChart ? 1 : 5);
    const min = this.isPercentChart ? Math.max(0, Math.floor(rawMin - padding)) : Math.floor(rawMin - padding);
    const max = this.isPercentChart ? Math.min(100, Math.ceil(rawMax + padding)) : Math.ceil(rawMax + padding);
    return { min, max: Math.max(max, min + 1) };
  }

  get yTicks(): { y: number; label: string }[] {
    const { min, max } = this.yDomain;
    return [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const value = max - (max - min) * ratio;
      return { y: 18 + ratio * 160, label: this.formatValue(value) };
    });
  }

  /** Converts structured trend data into stable SVG points. */
  get pointList(): { x: number; y: number; label: string; displayValue: string; showLabel: boolean }[] {
    const { min, max } = this.yDomain;
    const span = Math.max(max - min, 1);
    const labelEvery = Math.max(1, Math.ceil(this.data.length / 6));
    return this.data.map((row, index) => {
      const value = Number(row[this.yKey]) || 0;
      const x = this.data.length === 1 ? 338 : 58 + (index * 560) / (this.data.length - 1);
      const y = 178 - ((value - min) / span) * 160;
      return {
        x,
        y,
        label: String(row[this.xKey] || ''),
        displayValue: this.formatValue(value),
        showLabel: index % labelEvery === 0 || index === this.data.length - 1
      };
    });
  }

  /** Serializes computed points for the SVG polyline. */
  get points(): string {
    return this.pointList.map((point) => `${point.x},${point.y}`).join(' ');
  }

  private formatValue(value: number): string {
    if (this.isPercentChart) {
      return `${value.toFixed(value % 1 ? 1 : 0)}%`;
    }
    if (this.isMoneyChart) {
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
    }
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
  }
}
