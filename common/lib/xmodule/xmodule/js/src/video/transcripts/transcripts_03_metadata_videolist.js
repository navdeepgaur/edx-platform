(function (window, undefined) {
    CMS.Views.Metadata.VideoList = CMS.Views.Metadata.AbstractEditor.extend({

        events : {
            'click .setting-clear' : 'clear',
            'keypress .setting-input' : 'showClearButton',
            'click .collapse-setting' : 'toggleAdditional'
        },

        templateName: 'metadata-videolist-entry',
        placeholders: {
            'webm': '.webm',
            'mp4': 'http://somesite.com/video.mp4',
            'youtube': 'http://youtube.com/'
        },

        initialize: function () {
            CMS.Views.Metadata.AbstractEditor.prototype.initialize
                .apply(this, arguments);

            this.component_id = this.$el.closest('.component').data('id');

            this.$el.on(
                'input', 'input',
                _.debounce(_.bind(this.inputHandler, this), 300)
            );

            this.messanger = new Transcripts.MessageManager({
                el: this.$el.find('.transcripts-status'),
                component_id: this.component_id
            });
        },

        getValueFromEditor: function () {
            return _.map(
                this.$el.find('.input'),
                function (ele) { return ele.value.trim(); }
            ).filter(_.identity);
        },

        getVideoObjectsList: function () {
            var parseLink = Transcripts.Utils.parseLink,
                values = this.getValueFromEditor(),
                arr = [],
                data;

            for (var i = 0, len = values.length; i < len; i += 1) {
                data = parseLink(values[i]);

                if (data.mode !== 'incorrect') {
                    arr.push(data);
                }
            }

            return arr;
        },

        setValueInEditor: function (value) {
            var parseLink = Transcripts.Utils.parseLink,
                list = this.$el.find('.input'),
                val = value.filter(_.identity),
                placeholders = this.getPlaceholders(val);

            for (var i = 0; i < 3; i += 1) {
                list.eq(i)
                    .val(val[i] || null)
                    .attr('placeholder', placeholders[i]);
            }

            if (val.length > 1 || parseLink(val[0]).mode === 'html5') {
                this.openAdditional();
            } else {
                this.closeAdditional();
            }
        },

        getPlaceholders: function (value) {
            var parseLink = Transcripts.Utils.parseLink,
                placeholders = _.clone(this.placeholders),
                result = [],
                label, type;

            for (var i = 0; i < 3; i += 1) {
                type = parseLink(value[i]).type;

                if (placeholders[type]) {
                    label = placeholders[type];
                    delete placeholders[type];
                } else {
                    placeholders = _.values(placeholders);
                    label = placeholders.pop();
                }

                result.push(label);
            }

            return result;
        },

        openAdditional: function (event) {
            if (event && event.preventDefault) {
                event.preventDefault();
            }

            this.$el.find('.videolist-additional').addClass('is-visible');
        },

        closeAdditional: function (event) {
            if (event && event.preventDefault) {
                event.preventDefault();
            }

            this.$el.find('.videolist-additional').removeClass('is-visible');
        },

        toggleAdditional: function (event) {
            if (event && event.preventDefault) {
                event.preventDefault();
            }

            if (this.$el.find('.videolist-additional').hasClass('is-visible')) {
                this.closeAdditional.apply(this, arguments);
            } else {
                this.openAdditional.apply(this, arguments);
            }
        },

        inputHandler: function (event) {
            if (event && event.preventDefault) {
                event.preventDefault();
            }

            var entry = $(event.currentTarget).val(),
                data = Transcripts.Utils.parseLink(entry),
                isNotEmpty = Boolean(entry),
                $el = $(event.currentTarget);

            if (this.checkValidity(data, isNotEmpty)) {
                this.updateModel();
            } else if ($el.hasClass('videolist-url')) {
                this.closeAdditional();
            }
        },

        isUniq: function (dataList) {
            var arr = _.pluck(dataList, 'type'),
                uniqArr = _.uniq(arr);

            return arr.length === uniqArr.length;
        },

        checkValidity: function (data, showErrorModeMessage) {
            var self = this,
                dataList = this.getVideoObjectsList();

            if (!this.isUniq(dataList)) {
                this.messanger
                    .render('not_found')
                    .showError('Link types should be unique.', true);

                return false;
            }

            if (data.mode === 'incorrect' && showErrorModeMessage) {
                this.messanger
                    .render('not_found')
                    .showError('Incorrect url format.', true);

                return false;
            }

            this.fetchCaptions(dataList)
                .done(function (resp) {
                    if (resp.youtube_local && resp.youtube_server) {
                        self.messanger.render('conflict');
                    } else if (resp.youtube_local || resp.html5_local) {
                        self.messanger.render('found');
                    } else if (resp.youtube_server) {
                        self.messanger.render('on_youtube');
                    } else {
                        self.messanger.render('not_found');
                    }
                })
                .fail(function (resp) {
                    self.messanger.render('not_found');
                });

            console.log(data);
            return true;
        },

        fetchCaptions: function (dataList) {
            var data = this.prepareRequestData(dataList);

            if (this.xhr && this.xhr.abort) {
                this.xhr.abort();
            }

            this.xhr = $.ajax({
                url: '/check_subtitles',
                data: data,
                type: 'post'
            });

            return this.xhr;
        },

        prepareRequestData: function (data) {
            return $.extend({id: this.component_id}, {data: data});
        }
    });
}(this));
