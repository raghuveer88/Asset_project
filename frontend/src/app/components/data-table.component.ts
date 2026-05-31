import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ResponseComponent } from '../models/api.models';

@Component({
  selector: 'app-data-table',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="component-block">
      <h3>{{ component.title }}</h3>
      <p class="empty-state" *ngIf="!hasData">No data available for this view.</p>
      <div class="table-wrap" *ngIf="hasData">
        <table>
          <thead>
            <tr><th *ngFor="let col of columns">{{ label(col) }}</th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let row of rows">
              <td *ngFor="let col of columns">{{ value(row, col) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  `
})
export class DataTableComponent {
  @Input({ required: true }) component!: ResponseComponent;

  /** Uses backend-supplied column order so analytics tables stay predictable. */
  get columns(): string[] {
    return this.component.columns || [];
  }

  /** Normalizes table rows from the structured response component. */
  get rows(): Record<string, unknown>[] {
    return (this.component.rows || []) as Record<string, unknown>[];
  }

  get hasData(): boolean {
    return this.columns.length > 0 && this.rows.length > 0;
  }

  /** Converts API field names into readable table headers. */
  label(value: string): string {
    return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  /** Formats table cells, including currency-like numeric columns. */
  value(row: Record<string, unknown>, col: string): string {
    const value = row[col];
    if (typeof value === 'number' && (col.includes('rent') || col.includes('balance') || col.includes('amount'))) {
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
    }
    return value === null || value === undefined || value === '' ? '-' : String(value);
  }
}

