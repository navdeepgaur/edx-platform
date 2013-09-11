(function (window, undefined) {
    Transcripts.MessageManager = Backbone.View.extend({
        tagName: 'div',
        elClass: '.wrapper-transcripts-message',
        invisibleClass: 'is-invisible',

        templates: {
            not_found: '#transcripts-not-found', // 0: no found on both, type: HTML5, YT (no on yt)
            found: '#transcripts-found', // 1: on edx
            on_youtube: '#transcripts-on-youtube', // 2: no found on EDX, mode: YT
            conflict:  '#transcripts-conflict', // 3: add YT to existing HTML5 with subs, type: YT
            uploaded:  '#transcripts-uploaded', // when subtitles was uploaded, type: HTML5
            not_updated: '#transcripts-not-updated' // change source, type: HTML5
        },

        initialize: function () {
            this.fileUploader = new Transcripts.FileUploader({
                el: this.$el,
                messanger: this,
                component_id: this.options.component_id
            });
        },

        render: function (template) {
            var tpl = $(this.templates[template]).text();

            if (!tpl) {
                console.error('Couldn\'t load Transcripts status template');
            }
            this.template = _.template(tpl);
            this.$el
                .removeClass('is-invisible')
                .find(this.elClass).html(this.template({
                    component_id: encodeURIComponent(this.options.component_id)
                }));

            this.fileUploader.render();

            return this;
        },

        showError: function (err, hideButtons) {
            var $error = this.$el.find('.transcripts-error-message');

            if (err) {
                // Hide any other error messages.
                this.hideError();

                $error
                    .html(gettext(err))
                    .removeClass(this.invisibleClass);

                if (hideButtons) {
                    this.$el.find('.wrapper-transcripts-buttons')
                        .addClass(this.invisibleClass);
                }
            }
        },

        hideError: function () {
            this.$el.find('.transcripts-error-message')
                .addClass(this.invisibleClass);

            this.$el.find('.wrapper-transcripts-buttons')
                .removeClass(this.invisibleClass);
        }

    });
}(this));
