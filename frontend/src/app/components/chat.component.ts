import { AfterViewChecked, Component, ElementRef, EventEmitter, Input, Output, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { LucideRotateCcw, LucideSendHorizontal } from '@lucide/angular';
import { ChatMessage } from '../models/api.models';
import { MessageBubbleComponent } from './message-bubble.component';
import { LoadingStateComponent } from './loading-state.component';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MessageBubbleComponent,
    LoadingStateComponent,
    LucideSendHorizontal,
    LucideRotateCcw
  ],
  template: `
    <section class="chat-shell">
      <div class="chat-header">
        <div>
          <h2>Property workspace</h2>
          <p>Ask scoped questions about rent roll, website facts, or operational risk.</p>
        </div>
        <button class="icon-button" type="button" title="Reset chat" (click)="reset.emit()">
          <svg lucideRotateCcw></svg>
        </button>
      </div>

      <div class="messages" #messagesPane>
        <app-message-bubble
          *ngFor="let message of messages"
          [message]="message"
          (followup)="sendFollowup($event)">
        </app-message-bubble>
        <app-loading-state *ngIf="loading"></app-loading-state>
      </div>

      <form class="composer" (ngSubmit)="submit()">
        <textarea
          name="message"
          [(ngModel)]="draft"
          [disabled]="loading || !propertyCode"
          rows="2"
          placeholder="Ask about occupancy, lease expirations, balances, amenities, or management concerns">
        </textarea>
        <button class="send-button" type="submit" [disabled]="loading || !draft.trim() || !propertyCode" title="Send">
          <svg lucideSendHorizontal></svg>
        </button>
      </form>
    </section>
  `
})
export class ChatComponent implements AfterViewChecked {
  @Input({ required: true }) messages: ChatMessage[] = [];
  @Input() loading = false;
  @Input() propertyCode = '';
  @Output() send = new EventEmitter<string>();
  @Output() reset = new EventEmitter<void>();
  @ViewChild('messagesPane') private messagesPane?: ElementRef<HTMLDivElement>;

  draft = '';
  private lastMessageCount = 0;

  /** Keeps the newest assistant response and sticky composer in view. */
  ngAfterViewChecked(): void {
    if (this.messages.length !== this.lastMessageCount) {
      this.lastMessageCount = this.messages.length;
      queueMicrotask(() => {
        const pane = this.messagesPane?.nativeElement;
        if (pane) {
          pane.scrollTop = pane.scrollHeight;
        }
      });
    }
  }

  /** Emits the current draft as a chat message and clears the composer. */
  submit(): void {
    const message = this.draft.trim();
    if (!message) {
      return;
    }
    this.draft = '';
    this.send.emit(message);
  }

  /** Sends a clicked follow-up chip as the next same-property chat turn. */
  sendFollowup(question: string): void {
    this.send.emit(question);
  }
}
