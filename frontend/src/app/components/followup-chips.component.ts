import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Followup } from '../models/api.models';

@Component({
  selector: 'app-followup-chips',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="chips" *ngIf="followups.length">
      <button type="button" *ngFor="let followup of followups" (click)="selected.emit(followup.question)">
        {{ followup.label }}
      </button>
    </div>
  `
})
export class FollowupChipsComponent {
  @Input({ required: true }) followups: Followup[] = [];
  /** Emits the follow-up question so the parent can send it with the same property scope. */
  @Output() selected = new EventEmitter<string>();
}
