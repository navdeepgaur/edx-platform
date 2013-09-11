(function (window, undefined) {
    Transcripts.FileUploader = Backbone.View.extend({
        invisibleClass: 'is-invisible',
        validFileExtensions: ['srt'],

        events: {
            'change .file-input': 'changeHadler',
            'click .setting-upload': 'clickHandler'
        },

        uploadTpl: '#transcripts-file-upload',
        initialize: function () {
            _.bindAll(this);

            this.file = false;
            this.render();
        },

        render: function () {
            var tpl = $(this.uploadTpl).text(),
                tplContainer = this.$el.find('.transcripts-file-uploader');

            if (tplContainer) {
                if (!tpl) {
                    console.error('Couldn\'t load Transcripts File Upload template');
                }
                this.template = _.template(tpl);

                tplContainer.html(this.template({
                    ext: this.validFileExtensions,
                    component_id: this.options.component_id
                }));

                this.$statusBar = this.$el.find('.transcripts-message-status');
                this.$form = this.$el.find('.file-chooser');
                this.$input = this.$form.find('.file-input');
                this.$progress = this.$el.find('.progress-fill');
            }
        },

        upload: function () {
            if (!this.file) {
                return;
            }

            this.$form.ajaxSubmit({
                beforeSend: this.xhrResetProgressBar,
                uploadProgress: this.xhrProgressHandler,
                complete: this.xhrCompleteHandler
            });
        },

        clickHandler: function (event) {
            event.preventDefault();

            this.$input
                .val(null)
                .trigger('click');
        },

        uploadHadler: function (event) {
            event.preventDefault();

            this.upload();
        },

        changeHadler: function (event) {
            event.preventDefault();

            this.options.messanger.hideError();
            this.file = this.$input.get(0).files[0];

            if (this.checkExtValidity(this.file)) {
                this.upload();
            } else {
                this.options.messanger
                    .showError('Please select a file in .srt format.');
            }
        },

        checkExtValidity: function (file) {
            var fileExtension = file.name
                                    .split('.')
                                    .pop()
                                    .toLowerCase();

            if ($.inArray(fileExtension, this.validFileExtensions) !== -1) {
                return true;
            }

            return false;
        },

        xhrResetProgressBar: function () {
            var percentVal = '0%';

            this.$progress
                .width(percentVal)
                .html(percentVal)
                .removeClass(this.invisibleClass);
        },

        xhrProgressHandler: function (event, position, total, percentComplete) {
            var percentVal = percentComplete + '%';

            this.$progress
                .width(percentVal)
                .html(percentVal);
        },

        xhrCompleteHandler: function (xhr) {
            var resp = JSON.parse(xhr.responseText),
                err = (resp.error) ? resp.error : 'Uploading failed.';

            this.$progress
                .addClass(this.invisibleClass);

            if (xhr.status === 200 && resp.success) {
                this.options.messanger.render('uploaded');
            } else {
                // TODO Retrieve error form server
                this.options.messanger.showError(err);
            }
        }
    });
}(this));
