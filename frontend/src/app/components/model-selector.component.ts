import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-model-selector',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <label class="control-label" for="model">Model</label>
    <select id="model" class="control" [ngModel]="selected" (ngModelChange)="selectedChange.emit($event)">
      <option *ngFor="let model of models" [value]="model">{{ model }}</option>
    </select>
  `
})
export class ModelSelectorComponent {
  @Input({ required: true }) models: string[] = [];
  @Input({ required: true }) selected = 'gpt-4o-mini';
  /** Emits runtime model changes; the backend still validates the allow-list. */
  @Output() selectedChange = new EventEmitter<string>();
}
